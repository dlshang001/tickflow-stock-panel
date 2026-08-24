/**
 * 子路径部署辅助。
 *
 * vite.config.ts 的 base 决定应用挂载的公共前缀(如 '/stock/')。
 * - <Link>/<Navigate>/useNavigate() 由 react-router 的 basename 自动处理前缀。
 * - 但 window.location 直接赋值/比较属于浏览器原生跳转, 不经过 router,
 *   需要手动拼/剥前缀, 本文件提供统一工具。
 *
 * BASE_PATH: 去掉尾部斜杠的前缀 ('' 或 '/stock')。
 */
export const BASE_PATH = import.meta.env.BASE_URL.replace(/\/$/, '')

/** 给浏览器原生跳转路径补上 basename 前缀 (供 window.location 使用)。 */
export function withBase(path: string): string {
  if (!path.startsWith('/')) return path
  if (BASE_PATH && path.startsWith(BASE_PATH + '/')) return path
  return BASE_PATH + path
}

/**
 * 从完整 URL pathname 剥掉 basename, 返回 router 相对路径 (以 '/' 开头)。
 * 供把 window.location.pathname 喂回 useNavigate() 时使用。
 */
export function stripBase(pathname: string): string {
  if (BASE_PATH && pathname.startsWith(BASE_PATH + '/')) {
    return pathname.slice(BASE_PATH.length) || '/'
  }
  return pathname
}
