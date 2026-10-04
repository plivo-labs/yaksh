// Package skill holds SKILL.md, the guide for coding agents, so that "truman guide" prints the
// same text that agent tools load as a skill.
package skill

import _ "embed"

// Text is SKILL.md.
//
//go:embed SKILL.md
var Text string
