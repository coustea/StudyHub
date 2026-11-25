---
title: 第一个 Go 程序
order: 1
tags: [Go, 入门]
---

# 第一个 Go 程序

Go（又称 Golang）是 Google 开源的静态类型编译型语言，设计目标是简单、高效、适合并发。它的语法接近 C，但去掉了继承、泛型（1.18 前）、异常等复杂机制。

## 安装与验证

从 [go.dev/dl](https://go.dev/dl/) 下载对应平台的安装包，安装后验证：

```bash
go version
go env GOPATH GOMODCACHE
```

`GOPATH` 是旧版本的工作目录，Go 1.11 之后推荐用 **模块（module）** 管理项目，不再要求代码必须放在 GOPATH 下。

## 初始化模块

新建一个目录并执行：

```bash
mkdir hello-go && cd hello-go
go mod init example.com/hello
```

`go.mod` 记录模块路径和依赖版本，相当于 Go 项目的 `package.json`。

## 编写程序

创建 `main.go`：

```go
package main

import "fmt"

func main() {
    fmt.Println("Hello, Go!")
}
```

逐行解释：

| 代码 | 含义 |
|---|---|
| `package main` | 声明包名。可执行程序必须使用 `main` 包 |
| `import "fmt"` | 导入标准库中的格式化输入输出包 |
| `func main()` | 程序入口函数，无参数无返回值 |
| `fmt.Println` | 打印一行文本并换行 |

> Go 不需要分号结尾，编译器会自动插入。一行写多条语句时才需要显式分号，但通常不这么写。

## 运行与编译

```bash
go run main.go        # 直接编译并运行
go build              # 生成可执行文件
go build -o app       # 指定输出文件名
```

`go run` 适合开发调试，`go build` 生成二进制文件用于部署。Go 编译产物是静态链接的单个文件，不依赖目标机器的运行时环境。

## 包与可见性

- 同一目录下的文件必须声明同一个包名。
- 标识符首字母**大写**表示导出（其他包可访问），小写表示包内私有。
- 导入路径末尾的名称通常与包名一致，但变量名 `fmt` 来自 `package fmt`。

```go
import (
    "fmt"
    "strings"
)

func main() {
    fmt.Println(strings.ToUpper("hello"))
}
```

## 注释

```go
// 单行注释

/*
多行注释
*/
```

`go doc` 和编辑器提示依赖注释，导出函数建议写清楚用途。

## 小结

- [x] 用 `go mod init` 初始化模块
- [x] `main` 包 + `main` 函数构成可执行程序
- [x] 大写标识符对外可见，小写仅限包内
- [x] `go run` 运行，`go build` 编译
