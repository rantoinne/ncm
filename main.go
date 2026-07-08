package main

import (
	"flag"
	"fmt"
	"os"
	"reflect"
)

func main() {
	pathFlag := flag.String("path", "", "path to the file")
	flag.Parse()

	root := *pathFlag

	if root == "" {
		fmt.Println("Path is required")
		return
	}

	// Check if path exists
	info, err := os.Stat(root)

	if err != nil {
		fmt.Println("Path does not exist")
		return
	}

	if info.IsDir() {
		fmt.Println("Path is a directory")
		return
	} else {
		fmt.Println("Path is a file")
	}

	fmt.Printf("Hello, World! \n %v %v", root, reflect.TypeOf(pathFlag))
}
