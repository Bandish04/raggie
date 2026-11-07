// SPDX-License-Identifier: Apache-2.0

// Package pdfgen deterministically generates a text-heavy, bilingual (Turkish +
// English) PDF for the A3 ingestion benchmark. Same options → byte-identical
// file, with no external dependency or font file: it uses the standard
// Helvetica font with a custom encoding for the Turkish letters WinAnsi lacks
// (ğ Ğ ı İ ş Ş) and a ToUnicode map, so text extractors (pdfminer/pdfplumber,
// poppler) recover the exact text.
package pdfgen

import (
	"bytes"
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"
)

// Options controls the document.
type Options struct {
	Pages int    // default 50
	Seed  uint64 // content seed; the same seed yields the same bytes
}

const (
	pageWidth, pageHeight = 595, 842 // A4 in points
	margin                = 50
	fontSize, leading     = 10, 12
	wrapAt                = 92 // runes per line at 10pt Helvetica within the margins
	linesPerPage          = 58
)

// codes maps every rune the generator emits to its byte in the font encoding:
// ASCII as-is, WinAnsi's Latin-1 Turkish letters (incl. circumflex vowels), and the six letters WinAnsi
// lacks on otherwise unused codes (see differences).
var codes = func() map[rune]byte {
	m := map[rune]byte{}
	for r := rune(0x20); r <= 0x7e; r++ {
		m[r] = byte(r)
	}
	for r, b := range map[rune]byte{
		'ç': 0xe7, 'Ç': 0xc7, 'ö': 0xf6, 'Ö': 0xd6, 'ü': 0xfc, 'Ü': 0xdc,
		'â': 0xe2, 'Â': 0xc2, 'î': 0xee, 'û': 0xfb,
		'ğ': 0x81, 'Ğ': 0x8d, 'ı': 0x8f, 'İ': 0x90, 'ş': 0x9d, 'Ş': 0x9e,
	} {
		m[r] = b
	}
	return m
}()

const differences = "[129 /gbreve 141 /Gbreve 143 /dotlessi 144 /Idotaccent 157 /scedilla 158 /Scedilla]"

// rng is splitmix64: tiny, fast and stable forever (math/rand's sequences are
// not part of this package's determinism contract).
type rng struct{ s uint64 }

func (r *rng) next() uint64 {
	r.s += 0x9e3779b97f4a7c15
	z := r.s
	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb
	return z ^ (z >> 31)
}

// intn returns a value in [0, n) for the small positive n of the word lists.
func (r *rng) intn(n int) int {
	return int(r.next() % uint64(n)) // #nosec G115 -- n is a small positive length; the result is < n
}

var topics = [][2]string{
	{"Yıllık İzin ve Esnek Çalışma Politikası", "Annual Leave and Flexible Work Policy"},
	{"Bilgi Güvenliği ve Erişim Yönetimi", "Information Security and Access Management"},
	{"Satın Alma Onay Matrisi", "Procurement Approval Matrix"},
	{"Müşteri Şikâyet Yönetimi Süreci", "Customer Complaint Handling Process"},
	{"Yedekleme ve Felaket Kurtarma", "Backup and Disaster Recovery"},
	{"Kişisel Verilerin Korunması (KVKK)", "Personal Data Protection (KVKK)"},
	{"Ürün Yol Haritası ve Sürüm Planı", "Product Roadmap and Release Plan"},
	{"İş Sağlığı ve Güvenliği Eğitimleri", "Occupational Health and Safety Training"},
	{"Seyahat ve Harcırah Yönetmeliği", "Travel and Expense Regulation"},
	{"Tedarikçi Değerlendirme Ölçütleri", "Supplier Evaluation Criteria"},
}

var trSentences = []string{
	"Çalışanlar yıllık izin taleplerini en az %d iş günü önceden insan kaynakları portalı üzerinden iletmelidir.",
	"Bu prosedür, şirket genelindeki tüm birimler için bağlayıcıdır ve her yıl %d. ayda gözden geçirilir.",
	"Erişim yetkileri, görev değişikliği hâlinde %d saat içinde güncellenir ve bilgi güvenliği ekibince doğrulanır.",
	"Satın alma talepleri %d TL eşiğini aştığında finans direktörünün yazılı onayı gereklidir.",
	"Müşteri şikâyetleri kayıt altına alındıktan sonra en geç %d iş günü içinde çözüme kavuşturulmalıdır.",
	"Yedekler günlük olarak alınır; geri yükleme testleri her çeyrekte en az %d kez gerçekleştirilir.",
	"Kişisel veriler yalnızca belirlenen amaçlarla işlenir ve saklama süresi %d yılı aşamaz.",
	"Ürün ekibi, müşteri geri bildirimlerini önceliklendirerek her sürümde en az %d iyileştirme planlar.",
	"İş sağlığı ve güvenliği eğitimleri yeni başlayan personel için ilk %d gün içinde zorunludur.",
	"Yurt dışı seyahatlerinde günlük harcırah üst sınırı %d avro olarak uygulanır.",
	"Tedarikçiler kalite, teslimat ve fiyat ölçütlerine göre yılda %d kez puanlanır.",
	"Değişiklik talepleri, değişiklik danışma kurulunun haftalık toplantısında %d gün içinde karara bağlanır.",
	"Uzaktan çalışma, ekip yöneticisinin onayıyla haftada en fazla %d gün olarak planlanabilir.",
	"Güvenlik olayları tespit edildiği andan itibaren %d dakika içinde olay müdahale ekibine bildirilir.",
	"Şirket içi eğitim bütçesinin yüzde %d kadarı dijital yetkinlik programlarına ayrılmıştır.",
	"Sözleşme yenilemeleri, bitiş tarihinden en az %d gün önce hukuk birimine iletilmelidir.",
}

var enSentences = []string{
	"Employees must submit annual leave requests through the HR portal at least %d business days in advance.",
	"This procedure applies to every department and is reviewed each year during month %d.",
	"Access rights are updated within %d hours of a role change and verified by the security team.",
	"Purchase requests above %d TRY require the written approval of the finance director.",
	"Customer complaints must be resolved within %d business days after they are logged.",
	"Backups run daily, and restore drills are performed at least %d times per quarter.",
	"Personal data is processed only for stated purposes and retained for no longer than %d years.",
	"The product team prioritises customer feedback and plans at least %d improvements per release.",
	"Occupational safety training is mandatory for new staff within the first %d days.",
	"The daily allowance for international travel is capped at %d euros.",
	"Suppliers are scored on quality, delivery and price %d times a year.",
	"Change requests are decided by the change advisory board within %d days of submission.",
	"Remote work may be scheduled for up to %d days a week with the manager's approval.",
	"Security incidents are reported to the incident response team within %d minutes of detection.",
	"Around %d percent of the internal training budget is reserved for digital skills programmes.",
	"Contract renewals must reach the legal department at least %d days before the end date.",
}

// Pages returns the text lines of every page (already wrapped), the exact text
// Generate typesets.
func Pages(opts Options) [][]string {
	n := opts.Pages
	if n <= 0 {
		n = 50
	}
	r := &rng{s: opts.Seed}
	pages := make([][]string, 0, n)
	for p := 1; p <= n; p++ {
		topic := topics[(p-1)%len(topics)]
		lines := []string{
			fmt.Sprintf("Bölüm %d: %s", p, topic[0]),
			fmt.Sprintf("Section %d: %s", p, topic[1]),
		}
		for len(lines) < linesPerPage-2 {
			lang := trSentences
			if len(lines)%2 == 1 {
				lang = enSentences
			}
			var para strings.Builder
			fmt.Fprintf(&para, "%d.%d ", p, len(lines))
			for s := 0; s < 4; s++ {
				fmt.Fprintf(&para, lang[r.intn(len(lang))]+" ", 2+r.intn(90))
			}
			for _, l := range wrap(strings.TrimSpace(para.String()), wrapAt) {
				if len(lines) < linesPerPage-2 {
					lines = append(lines, l)
				}
			}
		}
		lines = append(lines, fmt.Sprintf("İşbu doküman Raggie bench için üretilmiştir; sayfa %d / %d, değişiklik kaydı %d.", p, n, r.intn(10000)))
		lines = append(lines, fmt.Sprintf("This synthetic document was generated for the Raggie benchmark; page %d of %d.", p, n))
		pages = append(pages, lines)
	}
	return pages
}

func wrap(s string, width int) []string {
	var out []string
	var line strings.Builder
	for _, w := range strings.Fields(s) {
		if line.Len() > 0 && utf8.RuneCountInString(line.String())+1+utf8.RuneCountInString(w) > width {
			out = append(out, line.String())
			line.Reset()
		}
		if line.Len() > 0 {
			line.WriteByte(' ')
		}
		line.WriteString(w)
	}
	if line.Len() > 0 {
		out = append(out, line.String())
	}
	return out
}

// pdfString encodes s for a literal string in the custom font encoding.
func pdfString(s string) string {
	var b strings.Builder
	b.WriteByte('(')
	for _, r := range s {
		c, ok := codes[r]
		if !ok {
			c = '?'
		}
		switch c {
		case '(', ')', '\\':
			b.WriteByte('\\')
			b.WriteByte(c)
		default:
			if c < 0x80 {
				b.WriteByte(c)
			} else {
				fmt.Fprintf(&b, "\\%03o", c)
			}
		}
	}
	b.WriteByte(')')
	return b.String()
}

func toUnicodeCMap() string {
	var b strings.Builder
	b.WriteString("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n" +
		"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n" +
		"/CMapName /RaggieBench-UCS def\n/CMapType 2 def\n" +
		"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n" +
		"1 beginbfrange\n<20> <7E> <0020>\nendbfrange\n")
	var extra []string
	for r, c := range codes {
		if c >= 0x80 {
			extra = append(extra, fmt.Sprintf("<%02X> <%04X>", c, r))
		}
	}
	sort.Strings(extra)
	fmt.Fprintf(&b, "%d beginbfchar\n%s\nendbfchar\n", len(extra), strings.Join(extra, "\n"))
	b.WriteString("endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n")
	return b.String()
}

// Generate renders the document as PDF 1.4 bytes.
func Generate(opts Options) []byte {
	pages := Pages(opts)
	var objs []string // objs[i] is object number i+1 (body without "N 0 obj")
	add := func(body string) int {
		objs = append(objs, body)
		return len(objs)
	}
	stream := func(dict, data string) string {
		return fmt.Sprintf("<< %s/Length %d >>\nstream\n%s\nendstream", dict, len(data), data)
	}

	catalog := add("") // filled once the page tree number is known
	pagesObj := add("")
	encoding := add("<< /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences " + differences + " >>")
	cmap := add(stream("", toUnicodeCMap()))
	font := add(fmt.Sprintf("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding %d 0 R /ToUnicode %d 0 R >>", encoding, cmap))
	info := add("<< /Title (Raggie A3 benchmark document) /Producer (raggie-bench pdfgen) >>")

	kids := make([]string, 0, len(pages))
	for _, lines := range pages {
		var c strings.Builder
		fmt.Fprintf(&c, "BT\n/F1 14 Tf\n%d TL\n%d %d Td\n", 18, margin, pageHeight-margin-14)
		fmt.Fprintf(&c, "%s Tj T*\n%s Tj T*\n/F1 %d Tf\n%d TL\n", pdfString(lines[0]), pdfString(lines[1]), fontSize, leading)
		for _, l := range lines[2:] {
			fmt.Fprintf(&c, "%s Tj T*\n", pdfString(l))
		}
		c.WriteString("ET")
		content := add(stream("", c.String()))
		page := add(fmt.Sprintf("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>",
			pagesObj, pageWidth, pageHeight, font, content))
		kids = append(kids, fmt.Sprintf("%d 0 R", page))
	}
	objs[catalog-1] = fmt.Sprintf("<< /Type /Catalog /Pages %d 0 R >>", pagesObj)
	objs[pagesObj-1] = fmt.Sprintf("<< /Type /Pages /Kids [%s] /Count %d >>", strings.Join(kids, " "), len(kids))

	var out bytes.Buffer
	out.WriteString("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
	offsets := make([]int, len(objs))
	for i, body := range objs {
		offsets[i] = out.Len()
		fmt.Fprintf(&out, "%d 0 obj\n%s\nendobj\n", i+1, body)
	}
	xref := out.Len()
	fmt.Fprintf(&out, "xref\n0 %d\n0000000000 65535 f \n", len(objs)+1)
	for _, off := range offsets {
		fmt.Fprintf(&out, "%010d 00000 n \n", off)
	}
	fmt.Fprintf(&out, "trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n", len(objs)+1, catalog, info, xref)
	return out.Bytes()
}
