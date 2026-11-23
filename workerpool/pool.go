package workerpool

import (
	"errors"
	"sync"
)

var (
	ErrClosed  = errors.New("workerpool is closed")
	ErrNilTask = errors.New("task cannot be nil")
)

type WorkerPool struct {
	maxWorkers int         // 最大 Worker 数量
	taskQueue  chan func() // 任务队列
	wg         sync.WaitGroup

	mu     sync.RWMutex
	closed bool
}

// NewWorkerPool 创建并启动 WorkerPool。
func NewWorkerPool(maxWorkers int) *WorkerPool {
	if maxWorkers <= 0 {
		maxWorkers = 1
	}

	pool := &WorkerPool{
		maxWorkers: maxWorkers,
		taskQueue:  make(chan func(), maxWorkers),
	}

	pool.run()
	return pool
}

// Submit 提交不需要返回值的任务。
func (w *WorkerPool) Submit(task func()) error {
	if task == nil {
		return ErrNilTask
	}

	w.mu.RLock()
	defer w.mu.RUnlock()

	if w.closed {
		return ErrClosed
	}

	w.taskQueue <- task
	return nil
}

// SubmitWithResult 提交带返回值的任务。
func (w *WorkerPool) SubmitWithResult[T any](
	task Task[T],
) (*Future[T], error) {
	if task == nil {
		return nil, ErrNilTask
	}

	// 创建任务对应的 Future
	future := &Future[T]{
		done: make(chan struct{}),
	}

	// 将泛型任务包装为普通 func()
	err := w.Submit(func() {
		value, taskErr := task()

		// 保存结果
		future.result = Result[T]{
			Value: value,
			Err:   taskErr,
		}

		// 通知任务执行完成
		close(future.done)
	})

	if err != nil {
		return nil, err
	}

	return future, nil
}

// Close 关闭任务队列并等待全部 Worker 退出。
func (w *WorkerPool) Close() {
	w.mu.Lock()

	if !w.closed {
		w.closed = true
		close(w.taskQueue)
	}

	w.mu.Unlock()
	w.wg.Wait()
}

// run 启动固定数量的 Worker。
func (w *WorkerPool) run() {
	for i := 0; i < w.maxWorkers; i++ {
		w.wg.Add(1)

		go func() {
			defer w.wg.Done()

			for task := range w.taskQueue {
				task()
			}
		}()
	}
}
