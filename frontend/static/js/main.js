// FinCheck - Premium Banking Client-Side Logic

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initMultiStepForm();
    highlightActiveLink();
});

// --- Theme Management ---
function initTheme() {
    const themeToggleBtn = document.getElementById('theme-toggle');
    if (!themeToggleBtn) return;
    
    const storedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', storedTheme);
    updateThemeIcon(storedTheme);
    
    themeToggleBtn.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        updateThemeIcon(newTheme);
        showToast(`Switched to ${newTheme} mode`, 'info');
    });
}

function updateThemeIcon(theme) {
    const icon = document.querySelector('#theme-toggle i');
    if (!icon) return;
    if (theme === 'dark') {
        icon.className = 'fas fa-sun';
    } else {
        icon.className = 'fas fa-moon';
    }
}

// --- Toast Notifications ---
function showToast(message, type = 'success') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let iconClass = 'fa-check-circle';
    if (type === 'error') iconClass = 'fa-times-circle';
    if (type === 'info') iconClass = 'fa-info-circle';
    
    toast.innerHTML = `
        <i class="fas ${iconClass}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    // Auto-remove toast after 4s
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse forwards';
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 4000);
}

// --- Active Link Highlight ---
function highlightActiveLink() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link, .sidebar-link');
    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href === currentPath) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}

// --- Multi-Step Application Form ---
function initMultiStepForm() {
    const form = document.getElementById('loan-apply-form');
    if (!form) return;
    
    const steps = Array.from(document.querySelectorAll('.form-step'));
    const indicators = Array.from(document.querySelectorAll('.step-indicator .step'));
    const progressBar = document.querySelector('.step-line-progress');
    const nextBtns = document.querySelectorAll('.btn-next');
    const prevBtns = document.querySelectorAll('.btn-prev');
    
    let currentStepIndex = 0;
    
    function showStep(index) {
        steps.forEach((step, idx) => {
            step.classList.toggle('active', idx === index);
        });
        
        indicators.forEach((indicator, idx) => {
            indicator.classList.toggle('active', idx === index);
            indicator.classList.toggle('completed', idx < index);
        });
        
        // Progress bar width
        if (progressBar) {
            const percent = (index / (steps.length - 1)) * 92; // Max width mapping
            progressBar.style.width = `${percent}%`;
        }
        
        currentStepIndex = index;
    }
    
    // Validate inputs in the current step
    function validateStep(stepIdx) {
        const stepElement = steps[stepIdx];
        const inputs = stepElement.querySelectorAll('input, select');
        let isValid = true;
        
        inputs.forEach(input => {
            if (input.hasAttribute('required') && !input.value.trim()) {
                isValid = false;
                input.style.borderColor = 'var(--danger)';
            } else {
                input.style.borderColor = 'var(--glass-border)';
            }
            
            // Email validation
            if (input.type === 'email' && input.value) {
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailRegex.test(input.value)) {
                    isValid = false;
                    input.style.borderColor = 'var(--danger)';
                    showToast('Please enter a valid email address.', 'error');
                }
            }
            
            // Number ranges validation
            if (input.type === 'number' && input.value) {
                const val = parseFloat(input.value);
                if (val < 0) {
                    isValid = false;
                    input.style.borderColor = 'var(--danger)';
                    showToast('Value cannot be negative.', 'error');
                }
            }
        });
        
        if (!isValid) {
            showToast('Please fill out all required fields correctly before continuing.', 'error');
        }
        return isValid;
    }
    
    nextBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (validateStep(currentStepIndex)) {
                showStep(currentStepIndex + 1);
            }
        });
    });
    
    prevBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            showStep(currentStepIndex - 1);
        });
    });
    
    form.addEventListener('submit', (e) => {
        if (!validateStep(currentStepIndex)) {
            e.preventDefault();
        }
    });
}
