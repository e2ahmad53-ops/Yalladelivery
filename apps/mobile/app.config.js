const role = process.env.EXPO_PUBLIC_APP_ROLE || 'store';
const captain = role === 'captain';
module.exports = {
  expo: {
    name: captain ? 'يلا دليفري كابتن' : 'يلا دليفري متجر',
    slug: captain ? 'yalla-delivery-captain' : 'yalla-delivery-store',
    version: '0.1.0',
    orientation: 'portrait',
    userInterfaceStyle: 'light',
    ios: {bundleIdentifier: captain ? 'com.yalladelivery.captain' : 'com.yalladelivery.store', supportsTablet: true},
    android: {package: captain ? 'com.yalladelivery.captain' : 'com.yalladelivery.store'},
    plugins: ['expo-secure-store', ...(captain ? [['expo-location', {locationWhenInUsePermission:'يلا دليفري يحتاج موقعك لتتبع التوصيل أثناء استخدام التطبيق.'}]] : [])]
  }
};
