//go:build darwin || linux

package prompt

import "golang.org/x/sys/unix"

// hideInput turns off echo on the terminal fd and keeps line input and Ctrl-C working. The
// returned func puts the terminal back as it was.
func hideInput(fd int) (restore func(), err error) {
	t, err := unix.IoctlGetTermios(fd, getTermios)
	if err != nil {
		return nil, err
	}
	saved := *t
	t.Lflag &^= unix.ECHO
	t.Lflag |= unix.ICANON | unix.ISIG
	t.Iflag |= unix.ICRNL
	if err := unix.IoctlSetTermios(fd, setTermios, t); err != nil {
		return nil, err
	}
	return func() { unix.IoctlSetTermios(fd, setTermios, &saved) }, nil
}
