#include <mutex>
#include <atomic>

/*
 * 示例 1：懒汉式 —— 线程不安全
 */
class Singleton {
private:
    Singleton() = default;
    Singleton(const Singleton&) = delete;
    Singleton& operator=(const Singleton&) = delete;

    static Singleton* m_instance;

public:
    static Singleton* getInstance() {
        if (m_instance == nullptr) {
            m_instance = new Singleton();
        }
        return m_instance;
    }
};

Singleton* Singleton::m_instance = nullptr;


/*
 * 示例 2：加锁的线程安全版本（但每次都加锁，代价高）
 */
class Singleton {
private:
    Singleton() = default;
    Singleton(const Singleton&) = delete;
    Singleton& operator=(const Singleton&) = delete;

    static Singleton* m_instance;
    static std::mutex m_mutex;

public:
    static Singleton* getInstance() {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_instance == nullptr) {
            m_instance = new Singleton();
        }
        return m_instance;
    }
};

Singleton* Singleton::m_instance = nullptr;
std::mutex Singleton::m_mutex;


/*
 * 示例 3：双重检查锁（DCLP）—— C++11 之前不安全
 * 原因：指令重排 / 内存可见性问题
 */
class Singleton {
private:
    Singleton() = default;
    Singleton(const Singleton&) = delete;
    Singleton& operator=(const Singleton&) = delete;

    static Singleton* m_instance;
    static std::mutex m_mutex;

public:
    static Singleton* getInstance() {
        if (m_instance == nullptr) {
            std::lock_guard<std::mutex> lock(m_mutex);
            if (m_instance == nullptr) {
                m_instance = new Singleton();
            }
        }
        return m_instance;
    }
};

Singleton* Singleton::m_instance = nullptr;
std::mutex Singleton::m_mutex;


/*
 * 示例 4：C++11 之后正确的 DCLP
 * 使用 atomic + memory fence
 */
class Singleton {
private:
    Singleton() = default;
    Singleton(const Singleton&) = delete;
    Singleton& operator=(const Singleton&) = delete;

    static std::atomic<Singleton*> m_instance;
    static std::mutex m_mutex;

public:
    static Singleton* getInstance() {
        Singleton* tmp = m_instance.load(std::memory_order_relaxed);
        std::atomic_thread_fence(std::memory_order_acquire);

        if (tmp == nullptr) {
            std::lock_guard<std::mutex> lock(m_mutex);
            tmp = m_instance.load(std::memory_order_relaxed);
            if (tmp == nullptr) {
                tmp = new Singleton();
                std::atomic_thread_fence(std::memory_order_release);
                m_instance.store(tmp, std::memory_order_relaxed);
            }
        }
        return tmp;
    }
};

std::atomic<Singleton*> Singleton::m_instance{nullptr};
std::mutex Singleton::m_mutex;


/*
 * 示例 5（补充）：C++11 推荐方式 —— Meyers Singleton
 * 最简单、最安全、最推荐
 */
class Singleton {
public:
    static Singleton& getInstance() {
        static Singleton instance;
        return instance;
    }

    Singleton(const Singleton&) = delete;
    Singleton& operator=(const Singleton&) = delete;

private:
    Singleton() = default;
};