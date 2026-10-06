//go:build !darwin && !linux

package prompt

import "errors"

// hideInput is not built for this system yet; "yaksha auth login --with-token" still works.
func hideInput(int) (func(), error) {
	return nil, errors.New("a hidden prompt does not work on this system; pass --with-token")
}
