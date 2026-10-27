package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"

	"gopkg.in/yaml.v3"
)

// readDocument returns a YAML or JSON file as JSON. A JSON file goes as it is. In YAML, each
// value except a null stays the text that the file has: a YAML decoder makes a plain
// 2027-01-15 a time and 0042 a number.
func readDocument(path string) ([]byte, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if json.Valid(content) {
		return content, nil
	}
	decoder := yaml.NewDecoder(bytes.NewReader(content))
	var root, next yaml.Node
	if err := decoder.Decode(&root); err != nil && !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	if err := decoder.Decode(&next); !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("%s holds more than one document: give one", path)
	}
	if err := asText(&root); err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	var value any
	if err := root.Decode(&value); err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	if value == nil {
		return nil, fmt.Errorf("%s is empty", path)
	}
	document, err := json.Marshal(value)
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	return document, nil
}

func asText(node *yaml.Node) error {
	switch node.Kind {
	case yaml.ScalarNode:
		if node.Tag != "!!null" && node.Tag != "!!merge" {
			node.Tag = "!!str"
		}
	case yaml.MappingNode:
		for i := 0; i < len(node.Content); i += 2 {
			key := node.Content[i]
			if key.Kind != yaml.ScalarNode {
				return fmt.Errorf("line %d: a key must be a name", key.Line)
			}
			if key.Tag != "!!merge" {
				key.Tag = "!!str"
			}
		}
	}
	for _, child := range node.Content {
		if err := asText(child); err != nil {
			return err
		}
	}
	return nil
}
