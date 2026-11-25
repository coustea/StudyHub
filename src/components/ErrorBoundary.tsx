import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * 兜底错误边界。
 *
 * 没有它的话，任何一个渲染期的异常（比如某条数据字段意外为 null）
 * 都会让 React 卸载整棵树，用户看到的是一片空白页面，控制台之外没有任何线索。
 * 这里把它收成一张可读的错误卡片，并保留「重试 / 回首页」两条出路。
 *
 * 注意：边界只能捕获渲染、生命周期与构造函数里的同步错误，
 * 事件处理与异步请求的错误仍然由各页面自己的 error state 处理。
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 生产环境没有堆栈上报服务，至少把组件栈留在控制台，方便贴到 issue 里
    console.error('[界面异常]', error, info.componentStack)
  }

  private reset = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="page">
        <div className="empty error-boundary">
          <span className="empty-title">这个页面出了点问题</span>
          <p>界面在渲染时遇到了异常，其他页面不受影响。可以先重试一次；如果反复出现，把浏览器控制台的报错记下来。</p>
          <pre className="error-boundary-detail">{error.message || String(error)}</pre>
          <div className="error-boundary-actions">
            <button className="btn btn-primary" onClick={this.reset}>重试</button>
            <a className="btn" href="/">回到首页</a>
          </div>
        </div>
      </div>
    )
  }
}
