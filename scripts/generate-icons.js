#!/usr/bin/env node
/**
 * Generate PNG icons from SVG
 */
const fs = require('fs');
const path = require('path');

async function generateIcons() {
  try {
    const sharp = require('sharp');

    const svgPath = path.join(__dirname, '..', 'resources', 'icons', 'icon.svg');
    const outputDir = path.join(__dirname, '..', 'resources', 'icons');

    if (!fs.existsSync(svgPath)) {
      console.error('SVG icon not found:', svgPath);
      process.exit(1);
    }

    const svgBuffer = fs.readFileSync(svgPath);

    // Generate app icon (512x512)
    await sharp(svgBuffer)
      .resize(512, 512)
      .png()
      .toFile(path.join(outputDir, 'icon.png'));
    console.log('Generated: icon.png (512x512)');

    // Generate tray icon (16x16, 32x32 for retina)
    await sharp(svgBuffer)
      .resize(16, 16)
      .png()
      .toFile(path.join(outputDir, 'tray-icon.png'));
    console.log('Generated: tray-icon.png (16x16)');

    // Generate macOS icon set sizes
    const macSizes = [16, 32, 64, 128, 256, 512];
    for (const size of macSizes) {
      await sharp(svgBuffer)
        .resize(size, size)
        .png()
        .toFile(path.join(outputDir, `icon-${size}.png`));
      console.log(`Generated: icon-${size}.png`);

      // Retina (@2x)
      if (size <= 256) {
        await sharp(svgBuffer)
          .resize(size * 2, size * 2)
          .png()
          .toFile(path.join(outputDir, `icon-${size}@2x.png`));
        console.log(`Generated: icon-${size}@2x.png`);
      }
    }

    console.log('\nAll icons generated successfully!');
  } catch (error) {
    console.error('Error generating icons:', error.message);
    process.exit(1);
  }
}

generateIcons();
