pub struct Signature {
    pub pattern: Vec<u8>,
    pub mask: Vec<bool>, 
}
impl Signature {
    pub fn from_ida(ida_sig: &str) -> Self {
        let mut pattern = Vec::new();
        let mut mask = Vec::new();
        for byte_str in ida_sig.split_whitespace() {
            if byte_str == "?" || byte_str == "??" {
                pattern.push(0);
                mask.push(false);
            } else if let Ok(val) = u8::from_str_radix(byte_str, 16) {
                pattern.push(val);
                mask.push(true);
            }
        }
        Self { pattern, mask }
    }
    #[inline(always)]
    pub fn matches(&self, slice: &[u8]) -> bool {
        if slice.len() < self.pattern.len() {
            return false;
        }
        for (i, (&p, &m)) in self.pattern.iter().zip(self.mask.iter()).enumerate() {
            if m && slice[i] != p {
                return false;
            }
        }
        true
    }
}
pub fn scan_pattern(data: &[u8], sig: &Signature) -> Option<usize> {
    if data.len() < sig.pattern.len() || sig.pattern.is_empty() {
        return None;
    }
    let end = data.len() - sig.pattern.len();
    for i in 0..=end {
        if sig.matches(&data[i..]) {
            return Some(i);
        }
    }
    None
}
pub fn scan_all_patterns(data: &[u8], sig: &Signature) -> Vec<usize> {
    let mut matches = Vec::new();
    if data.len() < sig.pattern.len() || sig.pattern.is_empty() {
        return matches;
    }
    let end = data.len() - sig.pattern.len();
    let mut i = 0;
    while i <= end {
        if sig.matches(&data[i..]) {
            matches.push(i);
            i += sig.pattern.len();
        } else {
            i += 1;
        }
    }
    matches
}
