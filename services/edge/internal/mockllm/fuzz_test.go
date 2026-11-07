// SPDX-License-Identifier: Apache-2.0

package mockllm

import (
	"regexp"
	"testing"
)

var citeRE = regexp.MustCompile(`\[(\d+)\]`)

// The mock only cites passage numbers that actually appear in the prompt.
func FuzzAnswerCitations(f *testing.F) {
	f.Add("CONTEXT:\n[1] (source: a.pdf, relevance: 0.9)\nx\n\n[2] (source: T - https://x)\ny", "q?")
	f.Add("[7] (kaynak: eski.pdf, alaka: 0.1)\n", "")
	f.Add("[1] (source: ", "[9] fake")
	f.Fuzz(func(t *testing.T, system, question string) {
		msgs := []map[string]any{{"role": "system", "content": system}, {"role": "user", "content": question}}
		got := Answer(msgs)
		labels := map[string]bool{}
		for _, m := range sourcePattern.FindAllStringSubmatch(system, -1) {
			labels[m[1]] = true
		}
		// Ignore numbers echoed from the user's own question.
		echoed := map[string]bool{}
		for _, m := range citeRE.FindAllStringSubmatch(question, -1) {
			echoed[m[1]] = true
		}
		for _, m := range citeRE.FindAllStringSubmatch(got, -1) {
			if !labels[m[1]] && !echoed[m[1]] {
				t.Fatalf("cited [%s] which is not a provided passage:\n%s", m[1], got)
			}
		}
	})
}
