/**
 * EduMate Client-Side Markdown & LaTeX Math Renderer
 * Redesigned to match the reference UI:
 * - Purple step badges for numbered lists (1, 2, 3)
 * - Dark navy code blocks with language tag and Copy button
 * - Lavender section banners for Algorithm / Steps
 * - Light green Example cards with green tags
 * - Complexity tables with green and blue pill badges
 * - Copy Response, Like, Dislike interactive handlers
 */

function escapeHtmlForMarkdown(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function fallbackClipboardCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '-9999px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
        document.execCommand('copy');
    } catch (e) {
        console.warn('execCommand copy failed:', e);
    }
    document.body.removeChild(ta);
}

function renderMarkdown(rawText) {
    if (!rawText) return '';
    let text = String(rawText);

    // Normalize newlines (CRLF -> LF)
    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    // 1. Extract and protect fenced code blocks ```lang\ncode\n```
    const codeBlocks = [];
    text = text.replace(/```([a-zA-Z0-9_-]*)[^\n]*\n([\s\S]*?)```/g, function (match, lang, code) {
        const placeholder = `@@@CODE_BLOCK_${codeBlocks.length}@@@`;
        const cleanLang = (lang || 'Code').trim();
        codeBlocks.push({
            lang: cleanLang,
            code: code.replace(/\n+$/, '')
        });
        return placeholder;
    });

    // 2. Extract and protect display math $$ ... $$
    const mathBlocks = [];
    text = text.replace(/\$\$([\s\S]*?)\$\$/g, function (match, math) {
        const placeholder = `@@@MATH_BLOCK_${mathBlocks.length}@@@`;
        mathBlocks.push(math.trim());
        return placeholder;
    });

    // 3. Extract and protect inline code `code`
    const inlineCodes = [];
    text = text.replace(/`([^`\n]+)`/g, function (match, inlineCode) {
        const placeholder = `@@@INLINE_CODE_${inlineCodes.length}@@@`;
        inlineCodes.push(inlineCode);
        return placeholder;
    });

    // 4. Extract and protect inline math $formula$
    const inlineMaths = [];
    text = text.replace(/\$([^\$\n\r]+?)\$/g, function (match, formula) {
        const placeholder = `@@@INLINE_MATH_${inlineMaths.length}@@@`;
        inlineMaths.push(formula.trim());
        return placeholder;
    });

    // 5. Escape general HTML (XSS prevention)
    text = escapeHtmlForMarkdown(text);

    // 6. Detect and format Example blockquotes / sections (> Example: or ### Example or **Example:**)
    text = text.replace(/(?:^|\n)(?:&gt;|###?|\*\*)\s*Example(?:\s*\d*)?:?\s*\**\s*\n([\s\S]*?)(?=\n(?:###|##|#|&gt;|$|\n\n))/gi, function (match, content) {
        let lines = content.trim().split('\n');
        let bodyHtml = lines.map(line => {
            line = line.replace(/^\s*[-*]\s*/, '→ ');
            line = line.replace(/(\[[^\]]+\])/g, '<span class="ai-example-highlight">$1</span>');
            return `<div class="ai-example-line">${line}</div>`;
        }).join('');
        return `\n<div class="ai-example-card"><div class="ai-example-header"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg><span>Example</span></div><div class="ai-example-body">${bodyHtml}</div></div>\n`;
    });

    // 7. Tables: Parse markdown tables with complexity pill detection
    text = text.replace(/((?:^|\n)\|[^\n]+\|\n\|[\s\-:|]+\|\n(?:\|[^\n]+\|(?:\n|$))+)/g, function (match) {
        const lines = match.trim().split('\n');
        if (lines.length < 2) return match;

        const headerLine = lines[0];
        const rows = lines.slice(2);

        const parseCells = (line) => {
            return line
                .replace(/^\|/, '')
                .replace(/\|$/, '')
                .split('|')
                .map(c => c.trim());
        };

        const headers = parseCells(headerLine);
        let tableHtml = '<div class="table-responsive"><table class="ai-table"><thead><tr>';
        headers.forEach(h => {
            tableHtml += `<th>${h}</th>`;
        });
        tableHtml += '</tr></thead><tbody>';

        rows.forEach(r => {
            if (!r.trim()) return;
            const cells = parseCells(r);
            tableHtml += '<tr>';
            cells.forEach((c, idx) => {
                let cellContent = c;
                // If it looks like complexity O(...)
                if (/O\([^\)]+\)/i.test(cellContent)) {
                    const badgeClass = idx === 0 ? 'complexity-pill-green' : 'complexity-pill-blue';
                    cellContent = cellContent.replace(/(O\([^\)]+\))/gi, `<span class="ai-complexity-pill ${badgeClass}">$1</span>`);
                }
                tableHtml += `<td>${cellContent}</td>`;
            });
            tableHtml += '</tr>';
        });

        tableHtml += '</tbody></table></div>';
        return '\n' + tableHtml + '\n';
    });

    // 8. Headings:
    // Heading with "Algorithm" or "Steps" -> banner
    text = text.replace(/^\s*###?\s*(Algorithm.*|Steps.*)/gim, '<div class="ai-section-banner"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg><span>$1</span></div>');
    // Heading with "Complexity" or "Time & Space" -> complexity heading with chart icon
    text = text.replace(/^\s*###?\s*(Time.*Complexity.*|Complexity.*)/gim, '<h4 class="ai-heading-complexity"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg><span>$1</span></h4>');
    // Main topic heading (# or ##)
    text = text.replace(/^\s*#\s+(.*$)/gim, '<h3 class="ai-topic-title"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg><span>$1</span></h3>');
    text = text.replace(/^\s*##\s+(.*$)/gim, '<h3 class="ai-topic-title"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg><span>$1</span></h3>');
    text = text.replace(/^\s*###\s+(.*$)/gim, '<h4 class="ai-heading-sub">$1</h4>');
    text = text.replace(/^\s*####\s+(.*$)/gim, '<h5 class="ai-heading-sub" style="font-size: 13px; font-weight: 600; color: #1e293b; margin: 12px 0 6px 0;">$1</h5>');

    // 9. Blockquotes: > quote or &gt; quote
    text = text.replace(/^\s*(?:&gt;|>)\s*(.*$)/gim, '<blockquote class="ai-blockquote">$1</blockquote>');

    // 10. Bold, Italic, Strikethrough
    text = text.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    text = text.replace(/___(.*?)___/g, '<strong><em>$1</em></strong>');
    text = text.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    text = text.replace(/\b_([^_]+)_\b/g, '<em>$1</em>');
    text = text.replace(/~~(.*?)~~/g, '<del>$1</del>');

    // 11. Lists: Ordered (with numbered purple circular badges 1, 2, 3) and Unordered
    text = text.replace(/(?:^|\n)(?:\d+\.\s+.+(?:\n\d+\.\s+.+)*)/g, function (listMatch) {
        const items = listMatch.trim().split('\n');
        let listHtml = '<div class="ai-steps-container">';
        items.forEach((item, idx) => {
            const clean = item.replace(/^\d+\.\s+/, '').trim();
            listHtml += `<div class="ai-step-row"><span class="ai-step-badge">${idx + 1}</span><div class="ai-step-text">${clean}</div></div>`;
        });
        listHtml += '</div>';
        return '\n' + listHtml + '\n';
    });

    text = text.replace(/(?:^|\n)(?:[-*]\s+.+(?:\n[-*]\s+.+)*)/g, function (listMatch) {
        const items = listMatch.trim().split('\n');
        let listHtml = '<ul class="ai-list">';
        items.forEach(item => {
            const clean = item.replace(/^[-*]\s+/, '').trim();
            listHtml += `<li>${clean}</li>`;
        });
        listHtml += '</ul>';
        return '\n' + listHtml + '\n';
    });

    // 12. Restore inline code (rendered as lavender tags or clean mono badges)
    inlineCodes.forEach((ic, idx) => {
        const placeholder = `@@@INLINE_CODE_${idx}@@@`;
        text = text.split(placeholder).join(`<span class="ai-tag-purple">${escapeHtmlForMarkdown(ic)}</span>`);
    });

    // 13. Restore inline math
    inlineMaths.forEach((m, idx) => {
        const placeholder = `@@@INLINE_MATH_${idx}@@@`;
        if (/O\([^\)]+\)/i.test(m)) {
            text = text.split(placeholder).join(`<span class="ai-complexity-pill complexity-pill-green">${escapeHtmlForMarkdown(m)}</span>`);
        } else {
            text = text.split(placeholder).join(`<span class="ai-math-inline" title="Formula">${escapeHtmlForMarkdown(m)}</span>`);
        }
    });

    // 14. Restore display math
    mathBlocks.forEach((m, idx) => {
        const placeholder = `@@@MATH_BLOCK_${idx}@@@`;
        text = text.split(placeholder).join(`<div class="ai-math-display">${escapeHtmlForMarkdown(m)}</div>`);
    });

    // 15. Restore fenced code blocks with dark navy styling, language tag and Copy Button
    codeBlocks.forEach((cb, idx) => {
        const placeholder = `@@@CODE_BLOCK_${idx}@@@`;
        const escapedCode = escapeHtmlForMarkdown(cb.code);
        const blockHtml = `
<div class="code-block-wrapper">
    <div class="code-block-header">
        <span class="code-block-lang">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2.2" style="vertical-align: middle; margin-right: 4px;"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            Code (${escapeHtmlForMarkdown(cb.lang || 'Code')})
        </span>
        <button type="button" class="code-copy-btn" onclick="copyCodeBlock(this)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            <span>Copy</span>
        </button>
    </div>
    <pre class="code-block-pre"><code class="language-${escapeHtmlForMarkdown(cb.lang)}">${escapedCode}</code></pre>
</div>`.trim();
        text = text.split(placeholder).join(blockHtml);
    });

    // 16. Convert double newlines to paragraph breaks
    const parts = text.split(/\n{2,}/);
    const htmlParts = parts.map(part => {
        part = part.trim();
        if (!part) return '';
        if (/^<(div|table|h3|h4|h5|ul|ol|blockquote|pre)/i.test(part)) {
            return part;
        }
        return `<p class="ai-para">${part.replace(/\n/g, '<br>')}</p>`;
    });

    return htmlParts.join('\n');
}

/**
 * Copies the raw code snippet from a code block to the user's clipboard
 */
function copyCodeBlock(buttonElem) {
    const wrapper = buttonElem.closest('.code-block-wrapper');
    if (!wrapper) return;
    const codeElem = wrapper.querySelector('code');
    if (!codeElem) return;

    const rawCode = codeElem.innerText || codeElem.textContent;

    function showSuccess() {
        const origContent = buttonElem.innerHTML;
        buttonElem.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
            <span style="color: #22c55e; font-weight: 600;">Copied!</span>
        `;
        buttonElem.classList.add('copied');
        setTimeout(() => {
            buttonElem.innerHTML = origContent;
            buttonElem.classList.remove('copied');
        }, 2000);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(rawCode).then(showSuccess).catch(() => {
            fallbackClipboardCopy(rawCode);
            showSuccess();
        });
    } else {
        fallbackClipboardCopy(rawCode);
        showSuccess();
    }
}

/**
 * Copies the entire assistant response text to the clipboard
 */
function copyResponseText(buttonElem) {
    const card = buttonElem.closest('.ai-response-card') || buttonElem.closest('.chat-assistant-row') || buttonElem.closest('.chat-assistant-container') || buttonElem.closest('.chat-bubble-assistant');
    if (!card) return;
    const bodyElem = card.querySelector('.markdown-rendered-body') || card.querySelector('.ai-msg-body') || card.querySelector('.ai-markdown-content');

    let textToCopy = '';
    if (bodyElem) {
        textToCopy = bodyElem.innerText || bodyElem.textContent;
    } else {
        const clone = card.cloneNode(true);
        const footer = clone.querySelector('.ai-response-footer');
        if (footer) footer.remove();
        textToCopy = clone.innerText || clone.textContent;
    }

    textToCopy = (textToCopy || '').trim();
    if (!textToCopy) return;

    function showSuccess() {
        const origText = buttonElem.innerHTML;
        buttonElem.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
            <span style="color: #16a34a; font-weight: 600;">Copied Response!</span>
        `;
        setTimeout(() => {
            buttonElem.innerHTML = origText;
        }, 2000);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textToCopy).then(showSuccess).catch(() => {
            fallbackClipboardCopy(textToCopy);
            showSuccess();
        });
    } else {
        fallbackClipboardCopy(textToCopy);
        showSuccess();
    }
}

/**
 * Feedback like button handler
 */
function toggleLike(buttonElem) {
    const isLiked = buttonElem.classList.contains('active-liked');
    const dislikeBtn = buttonElem.parentElement.querySelector('.action-btn-dislike');
    if (dislikeBtn) dislikeBtn.classList.remove('active-disliked');

    if (isLiked) {
        buttonElem.classList.remove('active-liked');
    } else {
        buttonElem.classList.add('active-liked');
    }
}

/**
 * Feedback dislike button handler
 */
function toggleDislike(buttonElem) {
    const isDisliked = buttonElem.classList.contains('active-disliked');
    const likeBtn = buttonElem.parentElement.querySelector('.action-btn-like');
    if (likeBtn) likeBtn.classList.remove('active-liked');

    if (isDisliked) {
        buttonElem.classList.remove('active-disliked');
    } else {
        buttonElem.classList.add('active-disliked');
    }
}
