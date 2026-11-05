package main

import (
	"fmt"
	"log"
	"net/http"
)

//TIP <p>To run your code, right-click the code and select <b>Run</b>.</p> <p>Alternatively, click
// the <icon src="AllIcons.Actions.Execute"/> icon in the gutter and select the <b>Run</b> menu item from here.</p>

func Index(w http.ResponseWriter, r *http.Request) {
	fmt.Println("Hello World")
}

func main() {
	http.HandleFunc("/", Index)
	err := http.ListenAndServe(":8080", nil)
	log.Fatal("Server started at :8080")
	if err != nil {
		fmt.Println(err)
		return
	}

}
