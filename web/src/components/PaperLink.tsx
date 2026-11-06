import Link from "next/link";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { slugFromId } from "@/lib/ids";
import { PUBLIC, withBase } from "@/lib/site";

/**
 * 链到论文详情页。公开站（D46）用普通链接整页打开：不预取、不需要详情页的 RSC 数据文件，
 * 构建后删掉 p/ 下的 .txt（每页三份，约占产物的六成）。旧站照旧用 <Link> 站内跳转。
 */
export function PaperLink({ id, children, ...rest }: { id: string; children: ReactNode } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const slug = slugFromId(id);
  if (PUBLIC) return <a href={withBase(`/p/${slug}/`)} {...rest}>{children}</a>;
  return <Link href={`/p/${slug}`} {...rest}>{children}</Link>;
}
