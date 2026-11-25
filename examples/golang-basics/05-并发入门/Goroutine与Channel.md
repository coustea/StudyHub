---
title: Goroutine 与 Channel
order: 1
tags: [Go, 并发, 进阶]
---

# Goroutine 与 Channel

Go 的并发模型建立在 goroutine 和 channel 之上。核心理念：**不要通过共享内存来通信，而要通过通信来共享内存**。

## Goroutine

goroutine 是轻量级线程，由 Go 运行时调度，初始栈只有几 KB，可以轻松创建上万个。

```go
go func() {
    fmt.Println("在 goroutine 中运行")
}()
```

`go` 关键字启动一个新 goroutine，函数立即返回，不等待结果。

```go
func worker(id int) {
    fmt.Println("worker", id)
}

go worker(1)
```

### 主 goroutine 不会等待

```go
func main() {
    go fmt.Println("hello")
    // main 退出，子 goroutine 可能还没来得及执行
}
```

需要同步机制等待任务完成。

## sync.WaitGroup

等待一组 goroutine 结束：

```go
var wg sync.WaitGroup

for i := 0; i < 5; i++ {
    wg.Add(1)
    go func(id int) {
        defer wg.Done()
        fmt.Println("worker", id)
    }(i)
}

wg.Wait()
```

要点：

- `Add(1)` 在启动 goroutine **之前**调用。
- `Done()` 用 defer 保证执行。
- `Wait()` 阻塞直到计数器归零。

## Channel

channel 是 goroutine 之间传递数据的管道，类型安全且自带同步。

```go
ch := make(chan int)        // 无缓冲
ch := make(chan int, 10)    // 缓冲大小 10
```

### 发送与接收

```go
ch := make(chan string)

go func() {
    ch <- "hello" // 发送
}()

msg := <-ch       // 接收
fmt.Println(msg)
```

无缓冲 channel 的发送和接收必须同时就绪，否则阻塞，因此天然完成同步。

### 关闭 channel

```go
close(ch)
```

接收方可以判断 channel 是否已关闭：

```go
v, ok := <-ch
if !ok {
    fmt.Println("channel 已关闭")
}
```

用 `range` 遍历直到关闭：

```go
for v := range ch {
    fmt.Println(v)
}
```

> 只由发送方关闭 channel，接收方不要关闭。向已关闭的 channel 发送会 panic。

### 单向 channel

用于约束函数权限：

```go
func producer(out chan<- int) {
    out <- 1
    close(out)
}

func consumer(in <-chan int) {
    for v := range in {
        fmt.Println(v)
    }
}
```

## select

`select` 同时在多个 channel 操作上等待，哪个就绪就执行哪个：

```go
select {
case msg := <-ch1:
    fmt.Println("ch1:", msg)
case msg := <-ch2:
    fmt.Println("ch2:", msg)
case <-time.After(time.Second):
    fmt.Println("超时")
}
```

要点：

- 多个 case 同时就绪时随机选择。
- `time.After` 常用于实现超时控制。
- 空的 `select {}` 会永久阻塞，可用于保持 main 不退出。
- `default` 分支让 select 非阻塞：没有就绪 case 时立即执行。

```go
select {
case msg := <-ch:
    fmt.Println(msg)
default:
    fmt.Println("暂无消息")
}
```

## 共享状态的保护

如果确实需要共享内存，使用互斥锁：

```go
var (
    mu    sync.Mutex
    count int
)

func increment() {
    mu.Lock()
    defer mu.Unlock()
    count++
}
```

读多写少用 `sync.RWMutex`：

```go
var mu sync.RWMutex

mu.RLock()
// 读操作
mu.RUnlock()
```

## 竞态检测

Go 内置竞态检测器，开发时务必开启：

```bash
go test -race ./...
go run -race main.go
```

它能发现未加锁的并发读写，是排查并发 bug 最有效的工具。

## 常见模式

### 流水线

```go
gen := func() <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for i := 0; i < 5; i++ {
            out <- i
        }
    }()
    return out
}

square := func(in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for v := range in {
            out <- v * v
        }
    }()
    return out
}

for v := range square(gen()) {
    fmt.Println(v)
}
```

### 工作池

```go
jobs := make(chan int, 100)
results := make(chan int, 100)

for w := 0; w < 4; w++ {
    go func() {
        for job := range jobs {
            results <- job * 2
        }
    }()
}
```

## 小结

- goroutine 轻量，由运行时调度，`go` 关键字启动。
- main 退出时不会等待其他 goroutine，需要 `WaitGroup` 或 channel 同步。
- 无缓冲 channel 提供同步语义，有缓冲 channel 解耦生产消费。
- 发送方负责关闭 channel，接收方用 `ok` 或 `range` 判断关闭。
- `select` 处理多路复用与超时。
- 共享状态用 `sync.Mutex`，并用 `-race` 检测竞态。
