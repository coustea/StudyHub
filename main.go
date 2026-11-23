package main

import (
	"fmt"

	"github.com/coustea/goforge/workerpool"
)

func add(a, b int) {
	fmt.Printf("add: %d + %d = %d\n", a, b, a+b)
}

func main() {
	pool := workerpool.NewWorkerPool(3)

	for i := 0; i < 1000000; i++ {
		pool.Submit(func() {
			add(i, i+3)
			
		})
	}

	// 关闭任务队列并等待所有 worker 跑完，否则 main 退出会丢掉还没执行的任务。
	pool.Close()
}
