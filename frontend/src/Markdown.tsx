import React from 'react';
import {safeHref} from './lib/format';

function inline(source: string): React.ReactNode[] {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^\s)]+\))/g;
  const result: React.ReactNode[] = [];
  let last = 0;
  for (const match of source.matchAll(pattern)) {
    const index = match.index || 0;
    if (index > last) result.push(source.slice(last, index));
    const value = match[0];
    if (value.startsWith('`')) result.push(<code key={index}>{value.slice(1, -1)}</code>);
    else if (value.startsWith('**')) result.push(<strong key={index}>{value.slice(2, -2)}</strong>);
    else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(value);
      const href = link ? safeHref(link[2]) : null;
      result.push(href && link ? <a key={index} href={href} target="_blank" rel="noopener noreferrer">{link[1]}</a> : value);
    }
    last = index + value.length;
  }
  if (last < source.length) result.push(source.slice(last));
  return result;
}

/** All text becomes React text nodes. Raw HTML, images and unsafe URL schemes are never interpreted. */
export default function Markdown({children}: {children: string}) {
  const lines = children.replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index++; continue; }
    if (/^\s*```/.test(line)) {
      const language = line.replace(/^\s*```/, '').trim();
      const code: string[] = [];
      index++;
      while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++]);
      index++;
      blocks.push(<div className="markdown-code" key={index}>{language && <span>{language}</span>}<pre><code>{code.join('\n')}</code></pre></div>);
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push(heading[1].length <= 2 ? <h3 key={index}>{inline(heading[2])}</h3> : <h4 key={index}>{inline(heading[2])}</h4>);
      index++; continue;
    }
    if (/^\s*(?:[-*+] |\d+\. )/.test(line)) {
      const ordered = /^\s*\d+\. /.test(line);
      const items: React.ReactNode[] = [];
      const pattern = ordered ? /^\s*\d+\. / : /^\s*[-*+] /;
      while (index < lines.length && pattern.test(lines[index])) {
        items.push(<li key={index}>{inline(lines[index].replace(pattern, ''))}</li>); index++;
      }
      blocks.push(ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>);
      continue;
    }
    if (line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const cells = (row: string) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
      const headers = cells(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) rows.push(cells(lines[index++]));
      blocks.push(<div className="table-scroll markdown-table" key={index}><table><thead><tr>{headers.map((cell, i) => <th key={i}>{inline(cell)}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{inline(cell)}</td>)}</tr>)}</tbody></table></div>);
      continue;
    }
    if (/^>\s?/.test(line)) { blocks.push(<blockquote key={index}>{inline(line.replace(/^>\s?/, ''))}</blockquote>); index++; continue; }
    if (/^\s*([-*_])\1\1+\s*$/.test(line)) { blocks.push(<hr key={index}/>); index++; continue; }
    const paragraph = [line]; index++;
    while (index < lines.length && lines[index].trim() && !/^\s*(#{1,6}\s|```|[-*+] |\d+\. |>)/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={index}>{inline(paragraph.join('\n'))}</p>);
  }
  return <div className="markdown">{blocks}</div>;
}
