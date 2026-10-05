// Package skill holds the truman skill, the guide for coding agents, so that "truman guide"
// prints the same text that agent tools load as a skill. The skill has its own folder, because
// skill installers copy the whole folder of a SKILL.md.
package skill

import _ "embed"

// Text is truman/SKILL.md.
//
//go:embed truman/SKILL.md
var Text string
