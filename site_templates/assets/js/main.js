document.addEventListener('DOMContentLoaded', function() {

    // FAQ accordion toggle
    document.querySelectorAll('.faq-question').forEach(function(btn) {
        btn.addEventListener('click', function() {
            this.parentElement.classList.toggle('active');
        });
    });

    // Bonus code copy-to-clipboard
    document.querySelectorAll('.bonus-code-copy').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var code = this.getAttribute('data-code');
            if (code && navigator.clipboard) {
                navigator.clipboard.writeText(code);
            }
        });
    });

    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            var target = document.querySelector(this.getAttribute('href'));
            if (target) target.scrollIntoView({ behavior: 'smooth' });
        });
    });

    // Hamburger menu toggle
    var hamburger = document.querySelector('.nav-hamburger');
    var navLinks = document.querySelector('.nav-links');
    if (hamburger && navLinks) {
        hamburger.addEventListener('click', function() {
            hamburger.classList.toggle('active');
            navLinks.classList.toggle('open');
            hamburger.setAttribute('aria-expanded',
                navLinks.classList.contains('open'));
        });

        // Mobile dropdown toggle (tap to open instead of hover)
        document.querySelectorAll('.nav-dropdown > a').forEach(function(link) {
            link.addEventListener('click', function(e) {
                if (window.innerWidth <= 768) {
                    e.preventDefault();
                    this.parentElement.classList.toggle('open');
                }
            });
        });
    }

});
