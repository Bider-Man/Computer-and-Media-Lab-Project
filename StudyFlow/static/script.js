document.addEventListener('DOMContentLoaded', () => {
    const themeBtn = document.getElementById('theme-toggle');
    const body = document.body;

    // Check if user has a saved theme in local storage
    const savedTheme = localStorage.getItem('studyflow-theme');
    if (savedTheme) {
        body.className = savedTheme;
    }

    // Toggle between themes when button is clicked
    themeBtn.addEventListener('click', () => {
        if (body.classList.contains('theme-cozy')) {
            body.className = 'theme-minimal';
            localStorage.setItem('studyflow-theme', 'theme-minimal');
        } else {
            body.className = 'theme-cozy';
            localStorage.setItem('studyflow-theme', 'theme-cozy');
        }
    });
});
