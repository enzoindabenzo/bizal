/** Minimal Jest config — jsdom environment so chatbot.js can build its
 * widget DOM and dispatch real events against it. */
module.exports = {
  testEnvironment: 'jsdom',
  testMatch: ['<rootDir>/static/js/__tests__/**/*.test.js'],
};
