// SPDX-License-Identifier: Apache-2.0

// Package sse is a minimal Server-Sent Events reader that stamps each event
// with its arrival time, for time-to-first-event measurements.
package sse

import (
	"bufio"
	"io"
	"strings"
	"time"
)

// Event is one dispatched SSE event. Name defaults to "message" (an event
// without an `event:` field, e.g. the edge's token deltas).
type Event struct {
	Name string
	Data string
	At   time.Time // when the event's terminating blank line was read
}

// maxLine bounds one SSE line (a `sources` event carries every chunk text).
const maxLine = 8 << 20

// Read parses r and calls fn for every event in arrival order. A non-nil error
// from fn stops reading and is returned.
func Read(r io.Reader, fn func(Event) error) error {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64<<10), maxLine)
	var (
		name string
		data []string
		has  bool
	)
	dispatch := func() error {
		if !has {
			return nil
		}
		e := Event{Name: name, Data: strings.Join(data, "\n"), At: time.Now()}
		if e.Name == "" {
			e.Name = "message"
		}
		name, data, has = "", nil, false
		return fn(e)
	}
	for sc.Scan() {
		line := strings.TrimSuffix(sc.Text(), "\r")
		if line == "" {
			if err := dispatch(); err != nil {
				return err
			}
			continue
		}
		if strings.HasPrefix(line, ":") {
			continue // comment / keep-alive
		}
		field, value, _ := strings.Cut(line, ":")
		value = strings.TrimPrefix(value, " ")
		switch field {
		case "event":
			name, has = value, true
		case "data":
			data, has = append(data, value), true
		}
	}
	if err := sc.Err(); err != nil {
		return err
	}
	return dispatch()
}
