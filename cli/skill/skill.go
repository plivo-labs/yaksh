// Package skill holds the yaksha skill, the guide for coding agents, so that "yaksha guide"
// prints the same text that agent tools load as a skill. The skill has its own folder, because
// skill installers copy the whole folder of a SKILL.md.
package skill

import _ "embed"

// Text is yaksha/SKILL.md.
//
//go:embed yaksha/SKILL.md
var Text string
