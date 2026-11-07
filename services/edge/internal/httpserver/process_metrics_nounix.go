// SPDX-License-Identifier: Apache-2.0

//go:build !unix

package httpserver

func processCPUSeconds() (float64, bool) { return 0, false }

func processMaxFDs() (uint64, bool) { return 0, false }
