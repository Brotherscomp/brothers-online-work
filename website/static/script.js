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
        closeNavigation();
      }
    });

    const closeNavigation = () => {
      nav.classList.remove('is-open');
      navToggle.setAttribute('aria-expanded', 'false');
      navToggle.setAttribute('aria-label', isAmharic ? 'ማውጫውን ክፈት' : 'Open navigation');
    };

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeNavigation();
    });

    window.addEventListener('resize', () => {
      if (window.innerWidth > 760) closeNavigation();
    });
  }

  const signUpForm = document.querySelector('#sign-up-form');
  if (signUpForm) {
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
  }

  const deviceRequestType = document.querySelector('#device-request-type');
  const deviceDetailsField = document.querySelector('.device-details-field');
  const deviceDetailsLabel = document.querySelector('.device-details-label');
  if (deviceRequestType && deviceDetailsField && deviceDetailsLabel) {
    const updateDeviceDetailsLabel = () => {
      deviceDetailsLabel.textContent = deviceRequestType.value === 'repair'
        ? deviceDetailsField.dataset.repairLabel
        : deviceDetailsField.dataset.purchaseLabel;
    };
    deviceRequestType.addEventListener('change', updateDeviceDetailsLabel);
    updateDeviceDetailsLabel();
  }
});
