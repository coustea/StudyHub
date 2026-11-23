package workerpool

import (
	"fmt"
	"sync"
)

type Task func()

type WorkerPool struct {
	maxWorkers int       // 最大 goroutine
	taskQueue  chan Task // 任务提交队列
	wg         sync.WaitGroup
}

func NewWorkerPool(maxWorkers int) *WorkerPool {
	if maxWorkers <= 0 {
		maxWorkers = 1
	}
	fmt.Printf("Creating worker pool with %d workers\n", maxWorkers)
	pool := &WorkerPool{
		maxWorkers: maxWorkers,
		taskQueue:  make(chan Task, maxWorkers),
	}
	pool.run()
	fmt.Printf("WorkerPool starting running....\n")
	return pool
}

// Submit 提交任务到队列。channel 本身并发安全，不需要额外加锁。
func (w *WorkerPool) Submit(task Task) {
	fmt.Printf("Submitting task to worker pool\n")
	w.taskQueue <- task
}

// Close 关闭任务队列并等待所有已提交的任务执行完毕。
func (w *WorkerPool) Close() {
	fmt.Printf("Closing worker pool\n")
	close(w.taskQueue)
	w.wg.Wait()
}

func (w *WorkerPool) run() {
	for i := 0; i < w.maxWorkers; i++ {
		w.wg.Add(1)
		go func() {
			defer w.wg.Done()
			for task := range w.taskQueue {
				fmt.Printf("Executing task in worker %d\n", i)
				task()
			}
		}()
	}
}
