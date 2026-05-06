pub fn rgb565(red: u8, green: u8, blue: u8) -> u16 {
    let red = ((red as u16) >> 3) & 0x1F;
    let green = ((green as u16) >> 2) & 0x3F;
    let blue = ((blue as u16) >> 3) & 0x1F;
    (red << 11) | (green << 5) | blue
}

#[derive(Debug, Clone)]
pub struct Framebuffer {
    width: usize,
    height: usize,
    pixels: Vec<u16>,
}

impl Framebuffer {
    pub fn new(width: usize, height: usize) -> Self {
        Self {
            width,
            height,
            pixels: vec![0; width * height],
        }
    }

    #[allow(dead_code)]
    pub fn width(&self) -> usize {
        self.width
    }

    #[allow(dead_code)]
    pub fn height(&self) -> usize {
        self.height
    }

    pub fn clear(&mut self, color: u16) {
        self.pixels.fill(color);
    }

    #[allow(dead_code)]
    pub fn pixel(&self, x: usize, y: usize) -> u16 {
        self.pixels[y * self.width + x]
    }

    #[allow(dead_code)]
    pub fn set_pixel(&mut self, x: usize, y: usize, color: u16) {
        if x < self.width && y < self.height {
            self.pixels[y * self.width + x] = color;
        }
    }

    pub fn fill_rect(&mut self, x: usize, y: usize, width: usize, height: usize, color: u16) {
        let max_x = x.saturating_add(width).min(self.width);
        let max_y = y.saturating_add(height).min(self.height);
        for row in y..max_y {
            let row_start = row * self.width;
            for col in x..max_x {
                self.pixels[row_start + col] = color;
            }
        }
    }

    pub fn paste_be_bytes_region(
        &mut self,
        x: usize,
        y: usize,
        width: usize,
        height: usize,
        pixel_data: &[u8],
    ) {
        if pixel_data.len() != width * height * 2 {
            return;
        }
        let max_x = x.saturating_add(width).min(self.width);
        let max_y = y.saturating_add(height).min(self.height);
        for row in y..max_y {
            let source_row = row - y;
            let row_start = row * self.width;
            for col in x..max_x {
                let source_col = col - x;
                let source_index = (source_row * width + source_col) * 2;
                self.pixels[row_start + col] =
                    u16::from_be_bytes([pixel_data[source_index], pixel_data[source_index + 1]]);
            }
        }
    }

    #[allow(dead_code)]
    pub fn as_be_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(self.pixels.len() * 2);
        for pixel in &self.pixels {
            bytes.extend_from_slice(&pixel.to_be_bytes());
        }
        bytes
    }
}
