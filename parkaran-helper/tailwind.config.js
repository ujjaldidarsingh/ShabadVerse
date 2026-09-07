module.exports = {
  content: ['./templates/*.html', './static/js/*.js'],
  theme: {extend: {colors: {
    void: {DEFAULT: '#0f0d13'}, deep: {DEFAULT: '#161420'}, mid: {DEFAULT: '#1e1a2a'},
    star: {50:'#fefce8',100:'#fef9c3',200:'#fef08a',300:'#fde047',400:'#fbbf24',500:'#f59e0b',600:'#d97706',700:'#b45309',800:'#92400e',900:'#78350f'},
    nebula: {blue:'#3b82f6',purple:'#8b5cf6',cyan:'#06b6d4'},
    signal: {green:'#10b981',red:'#ef4444'}
  }}}
};
