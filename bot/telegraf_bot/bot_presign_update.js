require('dotenv').config();

// Updated bot snippet to use presigned PUT from backend
// This snippet replaces the direct S3 upload flow with: request presign -> PUT to presign URL

const axios = require('axios');
const FormData = require('form-data');

async function uploadFileUsingPresign(ctx, fileBuffer, filename, contentType) {
  // Request presigned URL from backend
  const BACKEND_PRESIGN = process.env.BACKEND_PRESIGN_URL || (process.env.BACKEND_URL + '/uploads/presign');
  const res = await axios.post(BACKEND_PRESIGN, { filename, content_type: contentType });
  if (res.status !== 200) throw new Error('Presign request failed');
  const { put_url, object_url, key } = res.data;

  // Upload via PUT
  await axios.put(put_url, fileBuffer, {
    headers: {
      'Content-Type': contentType,
    },
    maxContentLength: Infinity,
    maxBodyLength: Infinity,
  });

  return { object_url, key };
}

// Usage inside handleChannelPost:
// const buffer = await downloadFileFromTelegram(file.file_path);
// const { object_url } = await uploadFileUsingPresign(ctx, buffer, 'photo.jpg', 'image/jpeg');

module.exports = { uploadFileUsingPresign };