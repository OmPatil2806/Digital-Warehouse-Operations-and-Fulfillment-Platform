/**
 * In-memory storage for the access token.
 *
 * The token is deliberately NOT saved in localStorage/sessionStorage: anything stored
 * there can be read by injected scripts (XSS). After a page reload the token is gone,
 * and a new one is obtained from the httpOnly refresh-token cookie instead.
 */
let accessToken: string | null = null

export const tokenStore = {
  get(): string | null {
    return accessToken
  },
  set(token: string): void {
    accessToken = token
  },
  clear(): void {
    accessToken = null
  },
}
