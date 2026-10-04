//! Single-line plain-text diagnostics, never HTML or terminal control data.
pub fn single_line(text: &str) -> String {
    let mut output = String::new();
    for character in text.chars() {
        if character.is_control()
            || matches!(character, '\u{2028}' | '\u{2029}' | '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
        {
            output.extend(character.escape_default());
        } else {
            output.push(character);
        }
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejected_network_text_cannot_create_terminal_lines_or_escapes() {
        let escaped = single_line("example\nFORGED\r\u{1b}[2J\u{202e}host");
        assert!(escaped.contains("\\nFORGED\\r"));
        assert!(escaped.contains("\\u{1b}[2J"));
        assert!(escaped.contains("\\u{202e}"));
        assert!(!escaped.chars().any(char::is_control));
        assert_eq!(escaped.lines().count(), 1);
    }

    #[test]
    fn ordinary_russian_diagnostic_is_preserved() {
        let text = "Соединение с Telegram: 127.0.0.1:443";
        assert_eq!(single_line(text), text);
    }
}
