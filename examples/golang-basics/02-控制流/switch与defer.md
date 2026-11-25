---
title: switch 与 defer
order: 2
tags: [Go, 控制流]
---

# switch 与 defer

`switch` 让多分支判断更清晰，`defer` 则用于可靠地执行清理逻辑，两者都是 Go 的高频语法。

## switch 语句

### 基本形式

```go
score := 85

switch score / 10 {
case 9:
    fmt.Println("优秀")
case 8:
    fmt.Println("良好")
case 6, 7:
    fmt.Println("及格")
default:
    fmt.Println("不及格")
}
```

与 C 不同，**Go 的 case 默认不会贯穿**，命中后自动跳出，不需要写 `break`。

一个 case 可以匹配多个值，用逗号分隔。

### 条件表达式 switch

`switch` 后可以不跟表达式，此时每个 case 都是布尔条件：

```go
switch {
case score >= 90:
    fmt.Println("A")
case score >= 60:
    fmt.Println("B")
default:
    fmt.Println("C")
}
```

### 带初始化语句

```go
switch v := getScore(); {
case v > 90:
    fmt.Println("高分", v)
default:
    fmt.Println("普通", v)
}
```

### fallthrough

需要显式贯穿到下一个 case 时使用 `fallthrough`：

```go
switch 2 {
case 1:
    fmt.Println("one")
case 2:
    fmt.Println("two")
    fallthrough
case 3:
    fmt.Println("three")
}
// 输出 two 和 three
```

`fallthrough` 只能放在 case 的最后一句。

### 类型 switch

用于判断接口值的具体类型：

```go
var value interface{} = 42

switch v := value.(type) {
case int:
    fmt.Println("整数", v)
case string:
    fmt.Println("字符串", v)
default:
    fmt.Println("未知类型")
}
```

类型 switch 是处理 `interface{}` 的标准方式。

## defer 语句

`defer` 将其后的函数调用延迟到**当前函数返回前**执行：

```go
func main() {
    defer fmt.Println("最后执行")
    fmt.Println("先执行")
}
```

### 典型用途：资源释放

```go
f, err := os.Open("data.txt")
if err != nil {
    return err
}
defer f.Close()

// 后续所有逻辑都不用担心忘记关闭文件
```

无论函数正常返回还是中途 `return`，`defer` 都会执行。

### 后进先出

多个 `defer` 按**后进先出（LIFO）**顺序执行：

```go
defer fmt.Println("1")
defer fmt.Println("2")
defer fmt.Println("3")
// 输出 3 2 1
```

这契合资源嵌套释放的需求：后打开的资源先关闭。

### 参数在 defer 时求值

`defer` 语句执行时，函数参数就已经确定：

```go
i := 1
defer fmt.Println(i)
i = 2
// 输出 1
```

若需要延迟读取变量，使用闭包：

```go
i := 1
defer func() { fmt.Println(i) }()
i = 2
// 输出 2
```

### defer 与 return 的顺序

带命名返回值时，`defer` 可以修改返回值：

```go
func f() (result int) {
    defer func() { result++ }()
    return 1 // 实际返回 2
}
```

执行顺序是：设置返回值 → 执行 defer → 函数返回。

### 循环中的 defer

不要在大量循环中使用 `defer`，它会在函数返回时才统一执行，可能延迟资源释放：

```go
for _, file := range files {
    f, _ := os.Open(file)
    defer f.Close() // 所有文件会一直打开到函数结束
}
```

应该封装成函数，让每次迭代结束后立即释放：

```go
for _, file := range files {
    func() {
        f, _ := os.Open(file)
        defer f.Close()
        // 处理文件
    }()
}
```

## panic 与 recover

`panic` 用于表示不可恢复的严重错误，会终止当前函数并逐层向上展开栈。

`recover` 可以在 `defer` 中捕获 `panic`，恢复程序正常执行：

```go
func safe() {
    defer func() {
        if r := recover(); r != nil {
            fmt.Println("捕获异常:", r)
        }
    }()
    panic("something wrong")
}
```

普通错误处理应该使用 `error` 返回值，而不是 panic/recover。详情见「函数与错误处理」。

## 小结

- Go 的 `switch` 默认不贯穿，需要 `fallthrough` 显式声明。
- 类型 switch 是处理接口值的惯用手段。
- `defer` 保证清理逻辑执行，顺序为后进先出。
- `defer` 参数立即求值，闭包可延迟读取变量。
- `recover` 只在 `defer` 中有效，且不应替代常规错误处理。
