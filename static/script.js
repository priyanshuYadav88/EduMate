/**
 * EduMate Client-Side Script
 * Handles asynchronous UI interactions, task toggling, real-time search, and AI assistant chat.
 */

// 1. Toggle Task Completion Status
async function toggleTaskStatus(taskId) {
    const row = document.getElementById(`task-row-${taskId}`);
    const checkbox = row.querySelector('.task-checkbox');

    try {
        const response = await fetch(`/api/tasks/toggle/${taskId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error(`Server returned ${response.status}`);
        }

        const data = await response.json();
        if (data.success) {
            if (data.is_completed) {
                row.classList.add('completed');
            } else {
                row.classList.remove('completed');
            }

            // Dynamically update the Today's Tasks stat card count without page reload
            const statTasks = document.getElementById('statTodayTasks');
            if (statTasks) {
                statTasks.innerText = `${data.completed_count}/${data.total_count}`;
            }
        } else {
            alert('Failed to update task.');
            checkbox.checked = !checkbox.checked;
        }
    } catch (err) {
        console.error('Error updating task:', err);
        checkbox.checked = !checkbox.checked;
        alert('Connection error. Please try again.');
    }
}

// 2. Add Task Modal Controls
function openAddTaskModal() {
    const modal = document.getElementById('addTaskModal');
    if (modal) {
        modal.style.display = 'flex';
        document.getElementById('taskTitleInput')?.focus();
    }
}

function closeAddTaskModal() {
    const modal = document.getElementById('addTaskModal');
    if (modal) {
        modal.style.display = 'none';
        document.getElementById('taskTitleInput').value = '';
    }
}

// 3. Handle Add Task Form Submission
async function handleCreateTask(e) {
    e.preventDefault();
    const titleInput = document.getElementById('taskTitleInput');
    const subjectSelect = document.getElementById('taskSubjectSelect');
    const title = titleInput.value.trim();
    const subjectId = subjectSelect.value;

    if (!title) return;

    try {
        const response = await fetch('/api/tasks/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                title: title,
                subject_id: subjectId
            })
        });

        const data = await response.json();
        if (data.success) {
            closeAddTaskModal();
            // Reload page to recompute statistical cards and schedule accurately
            window.location.reload();
        } else {
            alert(data.error || 'Unable to save task.');
        }
    } catch (err) {
        console.error('Error adding task:', err);
        alert('Server connection error. Please try again.');
    }
}

// 4. Quick AI Prompt Suggestion Chip
function askAiPrompt(text) {
    const input = document.getElementById('aiChatInput');
    if (input) {
        input.value = text;
        const form = document.getElementById('aiChatForm');
        if (form) {
            form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    }
}

// 5. Handle AI Chat Query
async function handleAiChatSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('aiChatInput');
    const query = input.value.trim();
    if (!query) return;

    const chatBody = document.getElementById('aiChatBody');

    // Append User Message Bubble
    const userBubble = document.createElement('div');
    userBubble.className = 'ai-message-bubble';
    userBubble.style.justifyContent = 'flex-end';
    userBubble.innerHTML = `
        <div class="ai-message-content" style="background-color: #2563eb; color: #ffffff;">
            <p>${escapeHtml(query)}</p>
        </div>
    `;
    chatBody.appendChild(userBubble);
    input.value = '';
    chatBody.scrollTop = chatBody.scrollHeight;

    // Append Thinking Indicator Bubble
    const loadingBubble = document.createElement('div');
    loadingBubble.className = 'ai-message-bubble';
    loadingBubble.innerHTML = `
        <div class="ai-message-avatar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
        </div>
        <div class="ai-message-content">
            <p style="color: #94a3b8; font-style: italic;">Thinking...</p>
        </div>
    `;
    chatBody.appendChild(loadingBubble);
    chatBody.scrollTop = chatBody.scrollHeight;

    try {
        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: query })
        });

        const data = await response.json();
        chatBody.removeChild(loadingBubble);

        const aiBubble = document.createElement('div');
        aiBubble.className = 'ai-message-bubble';
        aiBubble.innerHTML = `
            <div class="ai-message-avatar">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
            </div>
            <div class="ai-message-content">
                <p>${escapeHtml(data.reply).replace(/\\n/g, '<br>')}</p>
            </div>
        `;
        chatBody.appendChild(aiBubble);
        chatBody.scrollTop = chatBody.scrollHeight;
    } catch (err) {
        console.error('AI chat error:', err);
        chatBody.removeChild(loadingBubble);
        const errorBubble = document.createElement('div');
        errorBubble.className = 'ai-message-bubble';
        errorBubble.innerHTML = `
            <div class="ai-message-content" style="background-color: #451a1a; color: #fecdd3;">
                <p>Failed to connect to the study assistant service.</p>
            </div>
        `;
        chatBody.appendChild(errorBubble);
    }
}

// Helper: Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.innerText = text;
    return div.innerHTML;
}

// 6. Global Topbar Search Filter
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('globalSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();
            const subjectItems = document.querySelectorAll('.subject-progress-item');
            const taskItems = document.querySelectorAll('.task-item');

            subjectItems.forEach(item => {
                const text = item.innerText.toLowerCase();
                item.style.display = text.includes(query) ? 'flex' : 'none';
            });

            taskItems.forEach(item => {
                const text = item.innerText.toLowerCase();
                item.style.display = text.includes(query) ? 'flex' : 'none';
            });
        });
    }
});

// 7. Toggle AI Assistant Panel Collapse / Expand
function toggleAiAssistantPanel() {
    const card = document.getElementById('ai-assistant-card');
    if (card) {
        card.classList.toggle('collapsed');
    }
}
