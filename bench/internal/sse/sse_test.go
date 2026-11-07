// SPDX-License-Identifier: Apache-2.0

package sse

import (
	"errors"
	"strings"
	"testing"
)

func TestReadDispatchesEventsOnBlankLine(t *testing.T) {
	stream := "event: meta\ndata: {\"conversation_id\":\"c1\"}\n\n" +
		": keep-alive comment\n\n" +
		"data: {\"delta\":\"Hel\"}\n\n" +
		"data: {\"delta\":\"lo\"}\r\n\r\n" +
		"event: done\ndata: {\"message_id\":\"m1\"}\n\n" +
		"data: first\ndata: second\n\n" +
		"data: [DONE]\n\n"
	var got []Event
	if err := Read(strings.NewReader(stream), func(e Event) error {
		got = append(got, e)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	want := []Event{
		{Name: "meta", Data: `{"conversation_id":"c1"}`},
		{Name: "message", Data: `{"delta":"Hel"}`},
		{Name: "message", Data: `{"delta":"lo"}`},
		{Name: "done", Data: `{"message_id":"m1"}`},
		{Name: "message", Data: "first\nsecond"},
		{Name: "message", Data: "[DONE]"},
	}
	if len(got) != len(want) {
		t.Fatalf("got %d events: %+v", len(got), got)
	}
	for i := range want {
		if got[i].Name != want[i].Name || got[i].Data != want[i].Data {
			t.Errorf("event %d = %+v, want %+v", i, got[i], want[i])
		}
		if got[i].At.IsZero() {
			t.Errorf("event %d has no arrival time", i)
		}
	}
}

func TestReadFlushesTrailingEventWithoutBlankLine(t *testing.T) {
	var got []Event
	_ = Read(strings.NewReader("event: done\ndata: x"), func(e Event) error {
		got = append(got, e)
		return nil
	})
	if len(got) != 1 || got[0].Name != "done" || got[0].Data != "x" {
		t.Fatalf("got %+v", got)
	}
}

func TestReadStopsOnCallbackError(t *testing.T) {
	stop := errors.New("stop")
	n := 0
	err := Read(strings.NewReader("data: a\n\ndata: b\n\n"), func(Event) error {
		n++
		return stop
	})
	if !errors.Is(err, stop) || n != 1 {
		t.Fatalf("err = %v, callbacks = %d", err, n)
	}
}

func TestReadAcceptsFieldsWithoutSpace(t *testing.T) {
	var got []Event
	_ = Read(strings.NewReader("event:sources\ndata:{}\n\n"), func(e Event) error {
		got = append(got, e)
		return nil
	})
	if len(got) != 1 || got[0].Name != "sources" || got[0].Data != "{}" {
		t.Fatalf("got %+v", got)
	}
}
