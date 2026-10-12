// Package skill holds the yaksh skill, the guide for coding agents, so that "yaksh guide"
// prints the same text that agent tools load as a skill. The skill has its own folder, because
// skill installers copy the whole folder of a SKILL.md.
package skill

import _ "embed"

// Text is yaksh/SKILL.md.
//
//go:embed yaksh/SKILL.md
var Text string
