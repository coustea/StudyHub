---
title: Map 与结构体
order: 2
tags: [Go, 复合类型]
---

# Map 与结构体

`map` 是键值对集合，结构体用于把相关字段组合成一个自定义类型。两者是 Go 建模业务数据的基础。

## map

### 声明与初始化

```go
var m map[string]int          // nil map，不能写入
m = make(map[string]int)

scores := map[string]int{
    "Alice": 90,
    "Bob":   85,
}
```

`nil` map 可以读取（返回零值），但不能写入，否则 panic：

```go
var m map[string]int
fmt.Println(m["a"]) // 0，安全
m["a"] = 1          // panic: assignment to entry in nil map
```

### 增删改查

```go
scores["Alice"] = 95    // 新增或更新
fmt.Println(scores["Alice"])

delete(scores, "Bob")   // 删除不存在的键不会报错
```

### comma ok 判断键是否存在

直接读取无法区分"键不存在"和"值为零值"：

```go
v, ok := scores["Alice"]
if ok {
    fmt.Println("找到", v)
}
```

惯用写法（if 初始化语句）：

```go
if v, ok := scores["Alice"]; ok {
    fmt.Println(v)
}
```

只想判断存在性时：

```go
if _, ok := scores["Alice"]; ok {
    // 存在
}
```

### 遍历

```go
for key, value := range scores {
    fmt.Println(key, value)
}
```

遍历顺序**不保证稳定**。如果需要按 key 排序，先取出 keys 再 `sort.Strings`。

```go
keys := make([]string, 0, len(scores))
for k := range scores {
    keys = append(keys, k)
}
sort.Strings(keys)
for _, k := range keys {
    fmt.Println(k, scores[k])
}
```

### map 的键类型

键必须是可以比较的类型：`string`、整数、布尔、指针、数组、接口（动态值可比较）。切片、map、函数不能作为键。

```go
m := map[[2]int]string{{1, 2}: "point"}
```

### map 是引用类型

```go
a := map[string]int{"x": 1}
b := a
b["x"] = 2
fmt.Println(a["x"]) // 2
```

赋值和传参共享同一份数据。需要拷贝时显式创建新 map。

## 结构体

### 定义与初始化

```go
type User struct {
    Name string
    Age  int
}
```

多种初始化方式：

```go
u1 := User{"Alice", 18}              // 按字段顺序，不推荐
u2 := User{Name: "Alice", Age: 18}   // 命名字段，推荐
u3 := User{Name: "Alice"}            // 未赋值字段为零值
```

指针形式：

```go
u := &User{Name: "Alice", Age: 18}
fmt.Println(u.Name) // Go 自动解引用
```

### 匿名字段与嵌套

```go
type Address struct {
    City string
}

type User struct {
    Name    string
    Address // 嵌入，提升字段
}

u := User{Name: "Alice", Address: Address{City: "Beijing"}}
fmt.Println(u.City) // Beijing，直接访问提升字段
```

### 可见性

字段名首字母大写表示导出，可被其他包访问：

```go
type User struct {
    Name string // 导出
    age  int    // 包内私有
}
```

### 方法

方法是带接收者的函数。接收者可以是值或指针：

```go
func (u User) Greet() string {
    return "Hi, " + u.Name
}

func (u *User) SetAge(age int) {
    u.Age = age
}
```

选择原则：

- 需要修改接收者 → 用指针接收者。
- 结构体较大或包含不可复制字段（如 `sync.Mutex`）→ 用指针接收者。
- 小结构体且不修改 → 值接收者也可以，但同一类型建议统一风格。

```go
u := User{Name: "Alice"}
u.SetAge(20)   // Go 自动取地址，等价于 (&u).SetAge(20)
fmt.Println(u.Greet())
```

### 结构体标签

标签用于告诉编码库如何映射字段，常见于 JSON：

```go
type User struct {
    Name string `json:"name"`
    Age  int    `json:"age,omitempty"`
}
```

```go
b, _ := json.Marshal(User{Name: "Alice"})
fmt.Println(string(b)) // {"name":"Alice"}
```

`omitempty` 表示零值时忽略该字段。

## 组合优于继承

Go 没有继承，通过嵌入实现组合：

```go
type Reader interface { Read() string }

type File struct{ name string }
func (f File) Read() string { return "content" }

type ReadWriter struct {
    File // 复用 File 的字段和方法
    name string
}
```

这是 Go 复用代码的主要方式，比继承更显式、更灵活。

## 小结

- `map` 必须初始化后才能写入，读取不存在的键返回零值。
- 用 `v, ok := m[k]` 区分零值和不存在。
- map 遍历顺序不稳定，需要排序时自己处理。
- 结构体通过导出字段控制可见性，通过方法添加行为。
- 需要修改接收者时用指针接收者。
- 标签 `json:"name,omitempty"` 是 JSON 序列化的常见写法。
