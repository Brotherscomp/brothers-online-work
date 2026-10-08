document.addEventListener('DOMContentLoaded', () => {
  const navToggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('#main-nav');

  if (navToggle && nav) {
    const isAmharic = document.documentElement.lang === 'am';
    navToggle.addEventListener('click', () => {
      const expanded = navToggle.getAttribute('aria-expanded') === 'true';
      navToggle.setAttribute('aria-expanded', String(!expanded));
      navToggle.setAttribute('aria-label', expanded
        ? (isAmharic ? 'ማውጫውን ክፈት' : 'Open navigation')
        : (isAmharic ? 'ማውጫውን ዝጋ' : 'Close navigation'));
      nav.classList.toggle('is-open', !expanded);
    });

    nav.addEventListener('click', (event) => {
      if (event.target.closest('a')) {
        nav.classList.remove('is-open');
        navToggle.setAttribute('aria-expanded', 'false');
        navToggle.setAttribute('aria-label', isAmharic ? 'ማውጫውን ክፈት' : 'Open navigation');
      }
    });
  }

  const signUpForm = document.querySelector('#sign-up-form');
  if (!signUpForm) return;

  const password = signUpForm.querySelector('#password');
  const confirmation = signUpForm.querySelector('#confirm_password');
  const error = signUpForm.querySelector('#password-error');

  signUpForm.addEventListener('submit', (event) => {
    const passwordsMatch = password.value === confirmation.value;
    error.hidden = passwordsMatch;
    if (!passwordsMatch) {
      event.preventDefault();
      confirmation.focus();
    }
  });

  confirmation.addEventListener('input', () => {
    error.hidden = true;
  });
});
