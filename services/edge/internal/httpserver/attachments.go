// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"encoding/base64"
	"strings"
)

// attachmentPrefixes are the only accepted attachment forms: an inline,
// base64-encoded raster image. A URL would be fetched by OpenAI-compatible
// servers (vLLM, LiteLLM) — SSRF from an anonymous widget — and SVG can carry
// script, so both are refused.
var attachmentPrefixes = []string{
	"data:image/png;base64,",
	"data:image/jpeg;base64,",
	"data:image/webp;base64,",
	"data:image/gif;base64,",
}

// validAttachment reports whether a is an image data URL of an accepted type
// whose payload is non-empty, valid standard base64, within maxAttachBytes.
func validAttachment(a attachment) bool {
	if a.Type != "image" || len(a.DataURL) > maxAttachBytes {
		return false
	}
	for _, prefix := range attachmentPrefixes {
		if payload, ok := strings.CutPrefix(a.DataURL, prefix); ok {
			if payload == "" {
				return false
			}
			_, err := base64.StdEncoding.DecodeString(payload)
			return err == nil
		}
	}
	return false
}

// validAttachments is false when any attachment is not acceptable; the request
// is then refused as a whole rather than silently dropping the image.
func validAttachments(as []attachment) bool {
	for _, a := range as {
		if !validAttachment(a) {
			return false
		}
	}
	return true
}
