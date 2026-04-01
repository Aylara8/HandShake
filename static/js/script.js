function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function appendChatBubble(thread, role, text) {
    const bubble = document.createElement('div');
    bubble.className = `ai-chat-bubble ${role}`;
    bubble.textContent = text;
    thread.appendChild(bubble);
    thread.scrollTop = thread.scrollHeight;
    return bubble;
}

async function typeMentorResponse(data) {
    const thread = document.getElementById('ai-chat-thread');
    if (!thread || !data || !Array.isArray(data.teaching_guide)) {
        return;
    }

    const stepsBubble = appendChatBubble(thread, 'assistant', '');
    const tipBubble = appendChatBubble(thread, 'assistant tip', '');
    const stepLines = data.teaching_guide.slice(0, 3);

    for (let index = 0; index < stepLines.length; index += 1) {
        const prefix = index === 0 ? '' : '\n';
        for (const char of prefix + stepLines[index]) {
            stepsBubble.textContent += char;
            await sleep(12);
        }
        await sleep(120);
    }

    const fullTip = `Mentor tip: ${data.mentor_tip}`;
    for (const char of fullTip) {
        tipBubble.textContent += char;
        await sleep(10);
    }
}

function createMusicNote() {
    const note = document.createElement('div');
    note.className = 'music-note';
    note.innerHTML = `
        <svg viewBox="0 0 32 32" aria-hidden="true">
            <path d="M21 5v14.4a5.3 5.3 0 1 1-2-4.1V9.3l-9 2.2v9.9a5.3 5.3 0 1 1-2-4.1V8.5L21 5z"></path>
        </svg>
    `;
    note.style.left = `${Math.random() * 100}%`;
    note.style.animationDuration = `${4.2 + Math.random() * 2.6}s`;
    note.style.animationDelay = `${Math.random() * 0.35}s`;
    note.style.setProperty('--note-drift', `${-80 + Math.random() * 160}px`);
    note.style.setProperty('--note-scale', `${0.7 + Math.random() * 0.9}`);
    return note;
}

function triggerMagic(effect) {
    if (effect === 'music_notes') {
        const layer = document.getElementById('magic-notes-layer');
        if (!layer) {
            return;
        }
        layer.innerHTML = '';
        for (let i = 0; i < 25; i += 1) {
            const note = createMusicNote();
            layer.appendChild(note);
            note.addEventListener('animationend', () => note.remove(), { once: true });
        }
        return;
    }

    if (effect === 'cyber_grid') {
        const overlay = document.getElementById('cyber-grid-overlay');
        if (!overlay) {
            return;
        }
        overlay.classList.remove('active');
        void overlay.offsetWidth;
        overlay.classList.add('active');
        setTimeout(() => overlay.classList.remove('active'), 1600);
        return;
    }

    if (effect === 'sparks') {
        const layer = document.getElementById('spark-burst-layer');
        const target = document.getElementById('product-image-shell');
        if (!layer) {
            return;
        }

        const rect = target
            ? target.getBoundingClientRect()
            : { left: window.innerWidth / 2, top: window.innerHeight / 2, width: 0, height: 0 };
        const originX = rect.left + (rect.width / 2);
        const originY = rect.top + (rect.height / 2);

        layer.innerHTML = '';
        for (let i = 0; i < 18; i += 1) {
            const spark = document.createElement('span');
            spark.className = 'spark-particle';
            spark.style.left = `${originX}px`;
            spark.style.top = `${originY}px`;
            spark.style.setProperty('--spark-x', `${-120 + Math.random() * 240}px`);
            spark.style.setProperty('--spark-y', `${-140 + Math.random() * 120}px`);
            spark.style.animationDelay = `${Math.random() * 0.12}s`;
            layer.appendChild(spark);
            spark.addEventListener('animationend', () => spark.remove(), { once: true });
        }
    }
}

async function fetchExpertData(itemQuery, question) {
    const response = await fetch('/api/expert', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            item_query: itemQuery,
            question: question
        })
    });

    const source = response.headers.get('X-Expert-Source') || 'unknown';
    const liveProviderAvailable = response.headers.get('X-Live-Provider-Available') === 'true';
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(payload.error || 'Expert request failed');
    }
    return { data: payload, source: source, liveProviderAvailable: liveProviderAvailable };
}

function initExpertChat() {
    const sidebar = document.getElementById('ai-expert-sidebar');
    const launcher = document.getElementById('ai-expert-launcher');
    const closeButton = document.getElementById('ai-expert-close');
    const form = document.getElementById('ai-expert-form');
    const input = document.getElementById('ai-expert-input');
    const submitButton = form ? form.querySelector('button[type="submit"]') : null;
    const thread = document.getElementById('ai-chat-thread');
    const status = sidebar ? sidebar.querySelector('.ai-expert-status') : null;

    if (!sidebar || !launcher || !form || !input || !thread || !submitButton) {
        return;
    }

    const itemQuery = (sidebar.dataset.expertQuery || '').trim();
    let isLoading = false;

    function openSidebar() {
        sidebar.classList.add('visible');
        launcher.classList.add('hidden');
        input.focus();
    }

    function closeSidebarIfEmpty() {
        sidebar.classList.remove('visible');
        launcher.classList.remove('hidden');
    }

    async function ask(question) {
        if (!itemQuery || !question || isLoading) {
            return;
        }

        isLoading = true;
        openSidebar();
        appendChatBubble(thread, 'user', question);
        if (status) {
            status.textContent = 'AI is thinking...';
        }
        submitButton.disabled = true;
        input.disabled = true;

        try {
            const result = await fetchExpertData(itemQuery, question);
            const data = result.data;
            sidebar.style.setProperty('--expert-accent', data.brand_color || '#14b8a6');
            if (status) {
                status.textContent = result.source === 'fallback'
                    ? (result.liveProviderAvailable
                        ? 'Answer ready - live providers did not respond in time, using fallback'
                        : 'Answer ready - no live API key is configured on the server, using fallback')
                    : `Answer ready - source: ${result.source}`;
            }
            await typeMentorResponse(data);
            triggerMagic(data.visual_effect);
        } catch (error) {
            appendChatBubble(thread, 'assistant error', error.message || 'AI could not answer that right now.');
            if (status) {
                status.textContent = 'Request failed';
            }
        } finally {
            isLoading = false;
            submitButton.disabled = false;
            input.disabled = false;
            thread.scrollTop = thread.scrollHeight;
            input.focus();
        }
    }

    launcher.addEventListener('click', openSidebar);
    if (closeButton) {
        closeButton.addEventListener('click', closeSidebarIfEmpty);
    }
    document.addEventListener('click', (event) => {
        if (!sidebar.classList.contains('visible')) {
            return;
        }
        const clickedInsideSidebar = sidebar.contains(event.target);
        const clickedLauncher = launcher.contains(event.target);
        if (!clickedInsideSidebar && !clickedLauncher) {
            closeSidebarIfEmpty();
        }
    });

    sidebar.querySelectorAll('.ai-quick-action').forEach((button) => {
        button.addEventListener('click', () => {
            ask(button.dataset.expertQuestion || '');
        });
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const question = input.value.trim();
        if (!question) {
            return;
        }
        input.value = '';
        ask(question);
    });

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeSidebarIfEmpty();
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const splash = document.getElementById('splash-screen');
    if (splash) {
        setTimeout(() => {
            splash.classList.add('fade-out');
            setTimeout(() => {
                splash.style.display = 'none';
            }, 800);
        }, 3500);
    }

    const themeBtn = document.getElementById('theme-toggle');
    const html = document.documentElement;
    if (themeBtn) {
        const themeIcon = themeBtn.querySelector('i');
        const savedTheme = localStorage.getItem('theme') || 'light';
        html.setAttribute('data-theme', savedTheme);
        updateThemeIcon(savedTheme);

        themeBtn.addEventListener('click', () => {
            const currentTheme = html.getAttribute('data-theme');
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            updateThemeIcon(newTheme);
        });

        function updateThemeIcon(theme) {
            if (theme === 'dark') {
                themeIcon.classList.replace('fa-moon', 'fa-sun');
            } else {
                themeIcon.classList.replace('fa-sun', 'fa-moon');
            }
        }
    }

    const userMenuBtn = document.querySelector('.user-menu-btn');
    const userDropdown = document.querySelector('.user-dropdown');
    if (userMenuBtn && userDropdown) {
        userMenuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            userDropdown.classList.toggle('show');
        });

        document.addEventListener('click', () => {
            userDropdown.classList.remove('show');
        });
    }

    const categoryItems = document.querySelectorAll('.category-item');
    const cards = document.querySelectorAll('.hs-card');
    categoryItems.forEach((item) => {
        item.addEventListener('click', () => {
            categoryItems.forEach((entry) => entry.classList.remove('active'));
            item.classList.add('active');

            const selectedCategory = item.getAttribute('data-category');
            cards.forEach((card) => {
                const cardCategory = card.getAttribute('data-category');
                card.style.display = (selectedCategory === 'all' || cardCategory === selectedCategory)
                    ? 'block'
                    : 'none';
            });
        });
    });

    initExpertChat();
});
