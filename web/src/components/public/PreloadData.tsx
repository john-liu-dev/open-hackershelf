/**
 * 直接打开页面时，和 JS 并行预加载这一页要读的数据文件（fresh.json、search-index.json），首屏内容早出来。
 * 不用 <link rel="preload"> 或 react-dom 的 preload()：它们会变成 RSC 数据里的提示，
 * 别的页面预取这一页时也会把数据文件下载一遍（每个页头都链到新鲜页）。
 * 内联脚本只在静态 HTML 里执行；站内跳转时 React 不执行它，数据由页面组件挂载后再取。
 */
export function PreloadData({ href }: { href: string }) {
  const js = `(function(){var l=document.createElement("link");l.rel="preload";l.as="fetch";l.crossOrigin="anonymous";l.href=${JSON.stringify(href)};document.head.appendChild(l)})()`;
  return <script dangerouslySetInnerHTML={{ __html: js }} />;
}
