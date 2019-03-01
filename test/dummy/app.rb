require 'sinatra'
get '/' do
  "This is dummy app. Label: #{ENV['LABEL']}"
end

get '/elb-check' do
  "This is dummy app. Label: #{ENV['LABEL']}"
end