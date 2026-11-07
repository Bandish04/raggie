// SPDX-License-Identifier: Apache-2.0

package websearch

import (
	"context"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strings"
	"testing"
	"unicode/utf8"
)

// forbiddenV4 is an independent oracle for IPv4 destinations the page reader
// must never reach (loopback, private, CGNAT incl. cloud metadata such as
// 100.100.100.200, link-local incl. 169.254.169.254, benchmarking, reserved,
// multicast, broadcast).
func forbiddenV4(a netip.Addr) bool {
	for _, p := range []string{
		"0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
		"172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15",
		"224.0.0.0/4", "240.0.0.0/4",
	} {
		if netip.MustParsePrefix(p).Contains(a) {
			return true
		}
	}
	return false
}

// forbiddenIP extends the oracle to IPv6, including every transition format
// that embeds an IPv4 address (IPv4-mapped/compatible, NAT64, 6to4, Teredo).
func forbiddenIP(a netip.Addr) bool {
	a = a.Unmap()
	if a.Is4() {
		return forbiddenV4(a)
	}
	if a.IsLoopback() || a.IsPrivate() || a.IsLinkLocalUnicast() || a.IsLinkLocalMulticast() ||
		a.IsInterfaceLocalMulticast() || a.IsMulticast() || a.IsUnspecified() {
		return true
	}
	// Transition formats can route to arbitrary IPv4 destinations (including
	// private ones), so the oracle treats the whole ranges as forbidden.
	b := a.As16()
	if [12]byte(b[:12]) == [12]byte{} { // ::a.b.c.d (IPv4-compatible)
		return true
	}
	for _, p := range []string{"64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"} {
		if netip.MustParsePrefix(p).Contains(a) { // NAT64, 6to4, Teredo
			return true
		}
	}
	return false
}

// The SSRF guard must never admit an address the oracle forbids.
func FuzzIsPublicIP(f *testing.F) {
	for _, s := range []string{
		"8.8.8.8", "127.0.0.1", "169.254.169.254", "100.100.100.200", "10.0.0.1", "::1",
		"::ffff:127.0.0.1", "::127.0.0.1", "64:ff9b::a9fe:a9fe", "2002:7f00:1::1", "2001:0:4136:e378::1",
		"fd00:ec2::254", "fe80::1", "2606:4700:4700::1111", "255.255.255.255",
	} {
		f.Add([]byte(net.ParseIP(s)))
	}
	f.Fuzz(func(t *testing.T, raw []byte) {
		ip := net.IP(raw)
		public := isPublicIP(ip)
		addr, ok := netip.AddrFromSlice(raw)
		if !ok {
			if public {
				t.Fatalf("malformed IP %x admitted", raw)
			}
			return
		}
		if public && forbiddenIP(addr) {
			t.Fatalf("guard admitted forbidden address %s", addr)
		}
	})
}

// The dialer refuses forbidden literal addresses before any connection
// attempt. Only forbidden addresses are exercised, and the context is already
// cancelled, so nothing can leave the host.
func FuzzPublicDialContextLiteral(f *testing.F) {
	for _, s := range []string{"127.0.0.1", "169.254.169.254", "[::1]", "[::ffff:10.0.0.1]", "[64:ff9b::7f00:1]", "localhost", "8.8.8.8"} {
		f.Add(s, "80")
	}
	f.Fuzz(func(t *testing.T, host, port string) {
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		h := strings.Trim(host, "[]")
		addr, err := netip.ParseAddr(h)
		if err != nil {
			return // only literal addresses: hostnames would need DNS
		}
		if !forbiddenIP(addr) {
			return // only forbidden destinations are exercised: nothing may be dialed
		}
		target := net.JoinHostPort(addr.String(), port)
		if _, _, err := net.SplitHostPort(target); err != nil {
			return // malformed port: rejected by address parsing, not the IP guard
		}
		conn, derr := publicDialContext(ctx, "tcp", target)
		if conn != nil {
			_ = conn.Close()
			t.Fatalf("dial unexpectedly succeeded for %s", addr)
		}
		if derr == nil || !strings.Contains(derr.Error(), "blocked") {
			t.Fatalf("forbidden %s not blocked by the guard: %v", addr, derr)
		}
	})
}

// Redirects never leave http/https.
func FuzzRedirectScheme(f *testing.F) {
	for _, s := range []string{"https://ok.example/x", "file:///etc/passwd", "gopher://x", "javascript:alert(1)", "HTTP://X"} {
		f.Add(s)
	}
	check := publicHTTPClient().CheckRedirect
	f.Fuzz(func(t *testing.T, raw string) {
		u, err := url.Parse(raw)
		if err != nil {
			return
		}
		err = check(&http.Request{URL: u}, nil)
		if allowed := u.Scheme == "http" || u.Scheme == "https"; !allowed && err == nil {
			t.Fatalf("redirect to scheme %q allowed", u.Scheme)
		}
	})
}

// CanonicalURL never panics, only yields http(s) URLs and is idempotent.
func FuzzCanonicalURL(f *testing.F) {
	for _, s := range []string{
		"https://Example.com:443/a?utm_campaign=x&b=2&fbclid=y#z", "http://[::1]:8080/", "ftp://x", "https://xn--e1afmkfd.xn--p1ai/",
		"https://example.com/%zz", "https://user:pass@host/", "https://host./?ref=1",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, raw string) {
		c := CanonicalURL(raw)
		if c == "" {
			return
		}
		if !strings.HasPrefix(c, "http://") && !strings.HasPrefix(c, "https://") {
			t.Fatalf("non-http canonical URL %q from %q", c, raw)
		}
		if again := CanonicalURL(c); again != c {
			t.Fatalf("not idempotent: %q -> %q -> %q", raw, c, again)
		}
	})
}

// HTML extraction and excerpting never panic and respect the rune budget.
func FuzzExtractHTMLAndExcerpt(f *testing.F) {
	f.Add([]byte("<html><head><title>T</title></head><body><p>Hello world. Second sentence!</p><script>x</script></body></html>"), "hello", 40)
	f.Add([]byte("<<<>>>&amp;&#xFFFFFF;<p"), "", 1)
	f.Fuzz(func(t *testing.T, raw []byte, question string, maxRunes int) {
		if len(raw) > 64<<10 {
			return
		}
		title, text := extractHTML(raw)
		_ = title
		if maxRunes < 1 || maxRunes > 4096 {
			return
		}
		ex := makeExcerpt(text, question, maxRunes)
		if utf8.ValidString(text) && utf8.RuneCountInString(ex) > maxRunes+1 { // +1 for an ellipsis
			t.Fatalf("excerpt has %d runes, budget %d", utf8.RuneCountInString(ex), maxRunes)
		}
	})
}
