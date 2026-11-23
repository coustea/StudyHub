package workerpool

type Task[T any] func() (T, error)

type Result[T any] struct {
	Value T
	Err   error
}

type Future[T any] struct {
	done   chan struct{}
	result Result[T]
}

func (f *Future[T]) Get() (T, error) {
	<-f.done
	return f.result.Value, f.result.Err
}
