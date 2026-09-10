package main

func Helper() string {
	return nested()
}

func nested() string {
	return "ok"
}

type Config struct {
	Name string
}

type Store interface {
	Get(key string) string
}
