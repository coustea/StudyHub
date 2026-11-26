const originalFetch = global.fetch

// 模拟各类 OpenAI 兼容服务的真实返回形态：
//   notes-ai.example.test  —— 标准 OpenAI 成功响应
//   spark-maas.example.test —— 讯飞 MaaS：HTTP 200 里带业务码，且思考内容单独放在 reasoning_content
//   spark-biz-error.example.test —— 讯飞 MaaS：HTTP 200 但 code 非 0（模型不存在等）
//   deepseek.example.test —— 标准 OpenAI 错误体，用于校验错误透传
const HOSTS = new Set([
  'notes-ai.example.test',
  'spark-maas.example.test',
  'spark-biz-error.example.test',
  'deepseek.example.test',
])

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

global.fetch = async (input, init) => {
  const url = new URL(String(input))
  if (!HOSTS.has(url.hostname)) {
    return originalFetch(input, init)
  }

  const request = JSON.parse(init.body)
  const auth = new Headers(init.headers).get('authorization')

  // SDK 必须把 Base URL 收敛成 /v1 或 /v2 前缀后再拼 /chat/completions，
  // 否则会出现 /chat/completions/chat/completions 的 404。
  const validPath = url.pathname === '/v1/chat/completions' || url.pathname === '/v2/chat/completions'

  if (url.hostname === 'deepseek.example.test') {
    if (auth !== 'Bearer deepseek-key') {
      return json({ error: { message: 'Authentication Fails, Your api key is invalid', type: 'authentication_error' } }, 401)
    }
    return json({ choices: [{ finish_reason: 'stop', message: { content: '# DeepSeek 笔记' } }] })
  }

  if (url.hostname === 'spark-biz-error.example.test') {
    // 讯飞在 HTTP 200 返回业务错误：code 非 0，没有 choices
    return json({ code: 10013, message: 'model not found: spark-x2.6', sid: 'test' })
  }

  if (url.hostname === 'spark-maas.example.test') {
    if (auth !== 'Bearer spark-key') {
      return json({ code: 10002, message: 'HMAC signature cannot be verified: apikey not found' }, 401)
    }
    if (!validPath) return json({ code: 404, message: 'not found' }, 404)
    // 思考型模型：正文为空、推理内容非空时也要能取到内容
    const thinkingOnly = request.messages?.some((m) => String(m.content).includes('思考'))
    return json({
      code: 0,
      model: request.model,
      choices: [{
        index: 0,
        finish_reason: 'stop',
        message: thinkingOnly
          ? { role: 'assistant', content: '', reasoning_content: '# 星火推理笔记' }
          : { role: 'assistant', content: '# 星火笔记' },
      }],
    })
  }

  // notes-ai.example.test：保持原有严格校验
  const valid = auth === 'Bearer submitted-key' &&
    request.model === 'test-model' && request.messages[1].content.includes('写一段笔记')
  return json(valid
    ? { choices: [{ finish_reason: 'stop', message: { content: '# 测试笔记' } }] }
    : { error: { message: 'wrong request' } }, valid ? 200 : 400)
}
