/**
 * 开源书书架（Phase 5，D48）的封面底色：按书架分类取，键是 "b-" + 分类（Cover 的 area 传这个）。
 * 用论文那套底色里的颜色，同一套丛书的感觉；不改 lib/cover.ts（它必须和设计稿原件逐字一致，见 tests/cover.test.ts）。
 */
export const BOOK_COLORS: Record<string, string> = {
  "b-intro": "#8f6516", // 编程入门
  "b-lang": "#6a2e66", // 编程语言
  "b-plt": "#2c4a7a", // 语言实现与理论
  "b-systems": "#2b5c86", // 系统与网络
  "b-data": "#1c2846", // 数据库
  "b-ml": "#1d6b66", // 机器学习与 AI
  "b-math": "#23493c", // 数学与信号
  "b-graphics": "#a84b2a", // 图形与游戏
  "b-eng": "#3d6a2c", // 软件工程
  "b-security": "#3a3c42", // 安全与密码学
};
