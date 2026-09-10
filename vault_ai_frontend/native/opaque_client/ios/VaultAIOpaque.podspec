Pod::Spec.new do |s|
  s.name             = 'VaultAIOpaque'
  s.version          = '0.1.0'
  s.summary          = 'Svaultai native OPAQUE and PBKDF2 client.'
  s.description      = 'Static Rust C-ABI client used by Flutter on iOS.'
  s.homepage         = 'https://svaultai.com'
  s.license          = { :type => 'Proprietary' }
  s.author           = { 'Svaultai' => 'support@svaultai.com' }
  s.source           = { :path => '.' }
  s.platform         = :ios, '13.0'
  s.vendored_frameworks = 'VaultAIOpaque.xcframework'
end
