package main

import (
	"fmt"

	"github.com/coustea/goforge/workerpool"
)

func add(a, b int) int {
	fmt.Printf("add: %d + %d = %d\n", a, b, a+b)
	return a + b
}

func main() {
	pool := workerpool.NewWorkerPool(4)
	defer pool.Close()

	for i := 0; i < 3; i++ {
		pool.SubmitWithResult(func() (int, error) {
			return add(i, i+3), nil
		})
	}
}
