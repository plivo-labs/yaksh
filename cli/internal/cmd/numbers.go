package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

func (a *app) numbersCmd() *cobra.Command {
	numbers := &cobra.Command{
		Use:   "numbers",
		Short: "The phone numbers that tests call from and receive calls on: what the console's Numbers page holds",
		Long: "The phone numbers of the Plivo account. A number is a test number when it is linked to the " +
			"receiving application in Settings. Yaksh never takes a number that another application receives.",
	}
	numbers.AddCommand(
		a.numbersListCmd(), a.numbersUseCmd(), a.numbersStopCmd(), a.numbersCheckCmd(), a.numbersAccountCmd(),
	)
	return numbers
}

func (a *app) numbersListCmd() *cobra.Command {
	var owner string
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List the numbers of the account with their owners, as the last check found them",
		Long: "List the numbers of the account with their owners, as the last check found them. " +
			"problem says why no test can get a number now. The owner of a number is test, free, " +
			"cx_agent (a Plivo CX agent), other (another application) or no_voice (it cannot take calls).",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			filter := api.Owner(owner)
			if owner != "" && !filter.Valid() {
				return fmt.Errorf("%q is not an owner: use test, free, cx_agent, other or no_voice", owner)
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.ListPhoneNumbersApiV1PhoneNumbersGet(cmd.Context()))
			if err != nil {
				return err
			}
			if owner != "" {
				if body, err = numbersOf(body, filter); err != nil {
					return err
				}
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	cmd.Flags().StringVar(&owner, "owner", "", "show only the numbers of this owner: test, free, cx_agent, other or no_voice")
	return cmd
}

// numbersOf keeps only the items of a phone number listing that have the owner, and every other
// field as the server sent it.
func numbersOf(body []byte, owner api.Owner) ([]byte, error) {
	var listing map[string]json.RawMessage
	var items []json.RawMessage
	if err := json.Unmarshal(body, &listing); err != nil {
		return nil, fmt.Errorf("read the numbers: %w", err)
	}
	if err := json.Unmarshal(listing["items"], &items); err != nil {
		return nil, fmt.Errorf("read the numbers: %w", err)
	}
	kept := []json.RawMessage{}
	for _, item := range items {
		var number struct {
			Owner api.Owner `json:"owner"`
		}
		if err := json.Unmarshal(item, &number); err != nil {
			return nil, fmt.Errorf("read the numbers: %w", err)
		}
		if number.Owner == owner {
			kept = append(kept, item)
		}
	}
	encoded, err := json.Marshal(kept)
	if err != nil {
		return nil, err
	}
	listing["items"] = encoded
	return json.Marshal(listing)
}

// numberChange is a command that changes one number and prints the listing that follows.
func (a *app) numberChange(
	use, short, long string,
	call func(c *api.Client, ctx context.Context, number string) (*http.Response, error),
) *cobra.Command {
	return &cobra.Command{
		Use:   use + " <number>",
		Short: short,
		Long:  long,
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(call(c, cmd.Context(), args[0]))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}

func (a *app) numbersUseCmd() *cobra.Command {
	return a.numberChange("use",
		"Make a free number a test number",
		"Make a free number a test number: Yaksh links it to the receiving application in Plivo. "+
			"Give the number with its country code, such as +14155550100. "+
			"Yaksh refuses a number that another application receives.",
		func(c *api.Client, ctx context.Context, number string) (*http.Response, error) {
			return c.UsePhoneNumberApiV1PhoneNumbersNumberUsePost(ctx, number)
		})
}

func (a *app) numbersStopCmd() *cobra.Command {
	return a.numberChange("stop",
		"Stop using a test number",
		"Stop using a test number: Yaksh removes its application in Plivo. "+
			"Yaksh refuses while a test holds the number, or while the number rests after a test.",
		func(c *api.Client, ctx context.Context, number string) (*http.Response, error) {
			return c.StopPhoneNumberApiV1PhoneNumbersNumberStopPost(ctx, number)
		})
}

func (a *app) numbersCheckCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "check",
		Short: "Read the numbers of the account again now, to see changes made in the Plivo console",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.CheckPhoneNumbersApiV1PhoneNumbersCheckPost(cmd.Context()))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}

func (a *app) numbersAccountCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "account",
		Short: "Show the phone account: its credentials, the receiving application and its problems",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetPhoneAccountApiV1PhoneAccountGet(cmd.Context()))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}
