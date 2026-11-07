// SPDX-License-Identifier: Apache-2.0

package vectorstore

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestCollectionNameMatchesContract(t *testing.T) {
	// contracts/ lives at the repo root: internal/vectorstore -> up 4.
	path := filepath.Join("..", "..", "..", "..", "contracts", "qdrant_collection.json")
	data, err := os.ReadFile(path) // #nosec G304 -- fixed repo-relative contract path in a test
	if err != nil {
		t.Fatal(err)
	}
	var contract struct {
		Vectors []struct {
			Dim  int    `json:"dim"`
			Name string `json:"name"`
		} `json:"vectors"`
	}
	if err := json.Unmarshal(data, &contract); err != nil {
		t.Fatal(err)
	}
	if len(contract.Vectors) == 0 {
		t.Fatal("contract has no vectors")
	}
	for _, v := range contract.Vectors {
		if got := CollectionName(v.Dim); got != v.Name {
			t.Errorf("dim %d: got %q, want %q", v.Dim, got, v.Name)
		}
	}
}
